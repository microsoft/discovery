#!/usr/bin/env python3
"""gds_assembly_utils.py -- real GDS streamout / assembly via KLayout, plus the
rest of the tapeout handoff bundle.

Scenarios:
  * streamout -- convert a routed/filled DEF (+ tech LEF + cell GDS) into a final
    GDSII, using KLayout's Python API (`pya.LayoutToDEF` reverse via def import,
    then merge cell GDS) driven from a generated script.
  * merge     -- merge multiple GDS files (macro/IP + top, and the foundry SEAL
    RING when one is supplied) into one GDS.
  * write_cdl -- emit the CDL netlist the foundry runs its own LVS against.

GDS, seal ring and CDL are grouped here on purpose: they are the tapeout PACKAGE,
they share a lifetime, and they are handed over together, so one agent owns the
handoff bundle rather than scattering it across the physical stages.

Writes the final GDS and reports top-cell name, layer count, and file size.
Node-aware where a layer map / cell GDS come from the PDK binding. Results conform
to the Common Design Envelope.
"""
import json
import os
import re
import shutil
import subprocess
import time

TOOL = "gds-assembly"
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
        if (low.endswith((".log", ".tcl", ".ys", ".sh", ".do", ".rb", ".py"))
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
          "- `results/` \u2014 the final GDSII (tapeout deliverable)",
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
        "tools_used": [{"name": "KLayout GDS", "version": _klayout_version()}],
        "pdk_binding": pdk_binding or "none", "assumptions": assumptions or [],
        "inputs_ref": inputs_ref or {}, "vplan": "not_applicable",
        "results": results or {}, "qor_metrics": qor or {},
        "signoff_evidence": signoff or {}, "margin": {"method": "gds_streamout"},
        "validation": validation or {"verdict": "review"},
        "provenance": provenance or {},
    }
    if error:
        env["error"] = error
    return env


def _run_klayout_script(script_body, tag):
    sp = os.path.join(_WORK_DIR, f"{tag}.py")
    with open(sp, "w") as f:
        f.write(script_body)
    cmd = ["klayout", "-b", "-r", sp]
    _save_run_command(cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_WORK_DIR)
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, f"{tag}.log"), "w").write(out)
    return proc, out


def _gds_stats(gds_path, want_top=None):
    """Return {top, cells, layers, has_top} for a written GDS via KLayout."""
    body = f"""import pya, json
ly = pya.Layout()
ly.read({json.dumps(gds_path)})
tops = [c.name for c in ly.top_cells()]
want = {want_top!r}
# Count TEXT LABELS across all layers. Pin/net names live on the metal LABEL
# purpose (e.g. Sky130 datatype 5); a streamed die with ports but 0 labels is a
# pin-labeling gap -- named top pins are what let downstream LVS match by name
# instead of collapsing to a graph-isomorphism automorphism.
labels = 0
for li in ly.layer_indexes():
    for c in ly.each_cell():
        for s in c.shapes(li).each():
            if s.is_text():
                labels += 1
stats = {{"top": tops[0] if tops else None, "cells": ly.cells(),
          "layers": len(list(ly.layer_indexes())), "labels": labels,
          "has_top": bool(want) and ly.cell(want) is not None}}
open({json.dumps(os.path.join(_OUTPUT_DIR, "gds_stats.json"))}, "w").write(json.dumps(stats))
"""
    proc, out = _run_klayout_script(body, "gds_stats")
    if proc.returncode != 0:
        raise RuntimeError(
            f"KLayout GDS statistics failed (exit {proc.returncode}); "
            "see gds_stats.log:\n" + out[-1500:])
    with open(os.path.join(_OUTPUT_DIR, "gds_stats.json"), encoding="utf-8") as stream:
        return json.load(stream)


def _pdk_fill_layers(magic_tech):
    """Return {map_layer_name: (gds_layer, gds_datatype)} for the node's FILL layers.

    Read from the PDK's Magic techfile, which declares them explicitly:

        layer MET1FILL m1fill
            ...
            calma 36 28

    These numbers are NOT derivable from the drawing layers. sky130 routes on
    66,67,68,69,70,71,72 but fills on 28,36,41,34,51,59 -- unordered, and not
    offset from the drawing layer by any constant. Anything that computes a fill
    layer instead of reading it is guessing, so this parses the PDK or returns {}.
    """
    try:
        lines = open(magic_tech, encoding="utf-8", errors="replace").read().splitlines()
    except Exception:
        return {}
    out = {}
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*layer\s+([A-Za-z0-9_]*FILL)\s", ln)
        if not m:
            continue
        # `calma <layer> <datatype>` belongs to the nearest following stanza.
        for nxt in lines[i + 1:i + 8]:
            if re.match(r"^\s*layer\s", nxt):
                break
            c = re.match(r"^\s*calma\s+(\d+)\s+(\d+)", nxt)
            if c:
                name = m.group(1).lower()[:-4]        # MET1FILL -> met1
                out.setdefault(name, (c.group(1), c.group(2)))
                break
    return out


def _map_has_fill_purpose(map_path):
    """True if the layer map declares a FILL/OPCFILL purpose on any layer.

    Interrogates the map that will actually be handed to KLayout, so the caller
    can fail closed on the map's CONTENT rather than on its provenance.
    """
    if not map_path or not os.path.exists(str(map_path)):
        return False
    try:
        for ln in open(str(map_path), encoding="utf-8", errors="replace"):
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split()
            if len(parts) < 4 or not (parts[-1].isdigit() and parts[-2].isdigit()):
                continue
            if {p.strip().upper() for p in parts[1].split(",")} & {"FILL", "OPCFILL"}:
                return True
    except Exception:
        return False
    return False


def _augment_map_with_fill(map_path, magic_tech=None):
    """Return (augmented_map_path, rows_added, reason) adding the node's FILL purpose.

    KLayout's LEF/DEF reader emits DEF FILLS on a `<layer>.FILL` purpose. Vendor
    maps commonly omit that purpose (sky130A.map carries NET/SPNET/PIN/VIA/LEFPIN/
    LEFOBS/LABEL and no FILL), and the reader then prints

        No mapping for layer 'met2', purpose 'FILL' - layer is ignored

    and DROPS the fill -- a warning, not an error, so streamout still reports
    success while the design silently loses every fill shape it just inserted.

    THE FILL LAYERS ARE READ FROM THE PDK, NOT COMPUTED. An earlier version of
    this routine pointed the FILL purpose at each layer's own routing row (the
    row carrying NET) on the reasoning that fill must sit on the drawing layer to
    count toward density. That was WRONG, and measurably so: fill is floating
    metal by construction, so putting it on the drawing layer made the signoff
    deck's floating-metal rule fire once per fill shape --

        m2.x 3, m3.x 239, m4.x 504, m5.x 117   == 863, exactly the fill count
        ("floating met3, must interact with via3 or via4")

    taking DRC from 0 to 971. sky130 declares dedicated *FILL layers precisely so
    density rules can see fill while connectivity rules do not. Deriving the
    numbers, however plausible the derivation, produced a design that could not
    sign off; reading them from the techfile is the only correct source.

    The vendor map is never modified; an augmented copy is written to the work
    dir. Returns (None, [], reason) when nothing needed adding or the fill layers
    could not be resolved, so the caller fails closed rather than shipping a GDS
    whose fill was invented or dropped.
    """
    try:
        lines = open(map_path, encoding="utf-8", errors="replace").read().splitlines()
    except Exception:
        return None, [], "layer map unreadable"
    pdk_fill = _pdk_fill_layers(magic_tech) if magic_tech else {}
    if not pdk_fill:
        return None, [], ("no FILL layers declared in the PDK Magic techfile "
                          f"({magic_tech or 'not provided'})")
    present, has_fill = set(), set()
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 4 or not (parts[-1].isdigit() and parts[-2].isdigit()):
            continue
        pset = {p.strip().upper() for p in parts[1].split(",")}
        present.add(parts[0])
        if "FILL" in pset or "OPCFILL" in pset:
            has_fill.add(parts[0])
    # Only map layers the bound map already knows about; never invent a layer.
    todo = sorted(n for n in present if n in pdk_fill and n not in has_fill)
    if not todo:
        return None, [], "layer map already carries a FILL purpose"
    out = list(lines)
    out += ["",
            "# --- appended by chip-gds-assembly: FILL purpose ---",
            "# layer/datatype read from the PDK Magic techfile (layer <X>FILL ->",
            "# calma <n> <dt>). Fill is FLOATING metal: it belongs on the node's",
            "# dedicated fill layer, NOT on the drawing layer, or the floating-",
            "# metal rule (mN.x) fires once per fill shape."]
    added = []
    for name in todo:
        num, dt = pdk_fill[name]
        out.append("%-8s%-25s%-4s%s" % (name, "FILL,OPCFILL", num, dt))
        added.append("%s->%s/%s" % (name, num, dt))
    dest = os.path.join(_WORK_DIR, "lefdef_with_fill.map")
    try:
        with open(dest, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(out) + "\n")
    except Exception as exc:
        return None, [], f"could not write augmented map: {exc}"
    return dest, added, ""


def _bterm_pin_labels(def_file):
    """Extract top-level port labels and their placement from a DEF PINS section.

    WHY THIS EXISTS. A GDS streamed from a DEF carries POLYGONS but no TEXT. LVS
    then has no way to know which shape is `clk` and which is `crc[0]`, so it
    falls back to matching the layout against the schematic by graph isomorphism
    alone. That works on a small, asymmetric design and fails exactly where it
    matters: a symmetric or highly regular block has many valid isomorphisms, so
    LVS either mismatches or -- worse -- reports a match with the ports permuted.
    A named port is also what makes an LVS report readable instead of a list of
    anonymous net numbers.

    The DEF PINS section is the authoritative source: it carries the port name,
    direction, layer and placement. Returns a list of
    {name, layer, x, y, direction, use} in DEF database units, plus the units.
    Returns ([], None) when there is no PINS section -- reported as unavailable
    rather than as "no labels needed"."""
    try:
        text = open(str(def_file), encoding="utf-8", errors="replace").read()
    except OSError:
        return [], None
    mu = re.search(r"^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", text, re.M)
    units = float(mu.group(1)) if mu else None
    ms = re.search(r"^\s*PINS\s+\d+\s*;(.*?)^\s*END\s+PINS", text, re.S | re.M)
    if not ms:
        return [], units
    pins = []
    # Each pin is a '- name + NET n ... + LAYER lyr ( x1 y1 ) ( x2 y2 ) + PLACED ( px py ) o'
    # record terminated by ';'. Split on the leading '- ' of each record.
    for rec in re.split(r"\n\s*-\s+", ms.group(1)):
        rec = rec.strip()
        if not rec:
            continue
        name = rec.split()[0]
        if name in (";", "END"):
            continue
        mlyr = re.search(r"\+\s*LAYER\s+(\S+)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)"
                         r"\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)", rec)
        mpl = re.search(r"\+\s*(?:PLACED|FIXED|COVER)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)", rec)
        if not mlyr or not mpl:
            continue
        # Label at the CENTRE of the pin rectangle, offset by its placement, so
        # the text sits inside the shape it names (an LVS extractor attaches a
        # label to the shape it falls on).
        x1, y1, x2, y2 = (int(mlyr.group(i)) for i in (2, 3, 4, 5))
        px, py = int(mpl.group(1)), int(mpl.group(2))
        mdir = re.search(r"\+\s*DIRECTION\s+(\w+)", rec)
        muse = re.search(r"\+\s*USE\s+(\w+)", rec)
        pins.append({
            "name": name.strip('"'),
            "layer": mlyr.group(1),
            "x": px + (x1 + x2) // 2,
            "y": py + (y1 + y2) // 2,
            "direction": (mdir.group(1) if mdir else None),
            "use": (muse.group(1) if muse else "SIGNAL"),
        })
    return pins, units


def _label_layers_from_map(map_file):
    """Return {routing_layer: (gds_layer, gds_datatype)} for TEXT/LABEL purposes.

    The label layer numbers are a NODE CONSTANT and are read from the PDK's own
    LEF/DEF layer map, never hard-coded here. sky130A.map declares them as, e.g.

        NAME    met3/LABEL,met3/LEFPIN   70  5

    so a port on met3 is labelled on 70/5. A node whose map declares no NAME rows
    yields {} and pin labelling is reported as unavailable rather than being
    written to an invented layer -- exactly the failure mode the fill-layer work
    already documented in this file."""
    out = {}
    if not map_file:
        return out
    try:
        text = open(str(map_file), encoding="utf-8", errors="replace").read()
    except OSError:
        return out
    for m in re.finditer(r"^\s*NAME\s+(\S+)\s+(\d+)\s+(\d+)\s*$", text, re.M):
        for token in m.group(1).split(","):
            lyr = token.split("/")[0].strip()
            if lyr and lyr not in out:
                out[lyr] = (int(m.group(2)), int(m.group(3)))
    return out


def _map_drawing_layers(map_file):
    """{routing_layer: (gds_layer, datatype)} for the PIN (else NET) purpose rows of
    a LEF/DEF .map -- the drawing-layer fallback when no LABEL/NAME row exists."""
    out, weak = {}, {}
    if not map_file:
        return out
    try:
        text = open(str(map_file), encoding="utf-8", errors="replace").read()
    except OSError:
        return out
    for m in re.finditer(r"^\s*(\S+)\s+([\w,]+)\s+(\d+)\s+(\d+)\s*$", text, re.M):
        purposes = m.group(2).upper().split(",")
        val = (int(m.group(3)), int(m.group(4)))
        if "PIN" in purposes:
            out.setdefault(m.group(1), val)
        elif "NET" in purposes or "DRAWING" in purposes:
            weak.setdefault(m.group(1), val)
    for k, v in weak.items():
        out.setdefault(k, v)
    return out


def _lyt_lefdef_layer_map(lyt):
    """{'metal2': (13, 0), 'metal2.LABEL': (13, 0), ...} from the LEF/DEF reader
    layer-map embedded in a KLayout .lyt technology (ORFS FreePDK45.lyt declares
    `'metal2.LABEL : 13/0'`, i.e. labels on the drawing layer's datatype 0)."""
    import html as _html
    if not lyt:
        return {}
    try:
        text = open(str(lyt), encoding="utf-8", errors="replace").read()
    except OSError:
        return {}
    m = re.search(r"<lefdef>.*?<layer-map>(.*?)</layer-map>", text, re.S)
    if not m:
        return {}
    out = {}
    for name, lnum, dnum in re.findall(r"'\s*([\w.$]+)\s*:\s*(\d+)\s*/\s*(\d+)\s*'",
                                       _html.unescape(m.group(1))):
        out.setdefault(name, (int(lnum), int(dnum)))
    return out


def _lyp_drawing_layers(lyp):
    """{routing_layer: (gds_layer, datatype)} from .lyp entries `metal2.drawing - 13/0`."""
    if not lyp:
        return {}
    try:
        text = open(str(lyp), encoding="utf-8", errors="replace").read()
    except OSError:
        return {}
    out = {}
    for name, lnum, dnum in re.findall(
            r"<name>\s*([\w$]+)\.drawing\s*-\s*(\d+)\s*/\s*(\d+)\s*</name>", text):
        out.setdefault(name, (int(lnum), int(dnum)))
    return out


def _resolve_lyp(params, binding, lyt):
    """Layer-properties file: caller/binding, else the one the .lyt names, else <lyt>.lyp."""
    explicit = (params.get("layer_props") or params.get("lyp")
                or binding.get("klayout_lyp") or binding.get("lyp")
                or (binding.get("layermap") if str(binding.get("layermap") or "")
                    .lower().endswith(".lyp") else None))
    if explicit:
        return explicit
    if not (lyt and os.path.exists(str(lyt))):
        return None
    try:
        text = open(str(lyt), encoding="utf-8", errors="replace").read()
    except OSError:
        text = ""
    m = re.search(r"<layer-properties_file>\s*([^<]+?)\s*</layer-properties_file>", text)
    candidates = []
    if m:
        candidates.append(os.path.join(os.path.dirname(str(lyt)),
                                       os.path.basename(m.group(1))))
    candidates.append(os.path.splitext(str(lyt))[0] + ".lyp")
    return next((c for c in candidates if os.path.exists(c)), None)


def _resolve_label_layers(lefdef_map, lyt, lyp, pin_layers):
    """Pick the GDS text layer for each pin routing layer, most specific first:
      1. LEF/DEF .map NAME row (dedicated label purpose, e.g. sky130 met3 -> 70/5)
      2. .lyt LEF/DEF layer-map `<layer>.LABEL : L/D` (FreePDK45: metal2 -> 13/0)
      3. NO label purpose declared -> the pin's DRAWING layer (.map PIN/NET row,
         .lyt `<layer> : L/D`, or .lyp `<layer>.drawing - L/D`). Text on the
         drawing layer is what most LVS decks attach a port name to; the choice is
         recorded per layer so a reviewer can see no label purpose existed.
    Returns ({layer: (L, D)}, {layer: source})."""
    from_map = _label_layers_from_map(lefdef_map)
    map_draw = _map_drawing_layers(lefdef_map)
    lyt_map = _lyt_lefdef_layer_map(lyt)
    lyp_draw = _lyp_drawing_layers(lyp)
    layers, how = {}, {}
    for lyr in sorted(set(pin_layers)):
        if lyr in from_map:
            layers[lyr], how[lyr] = from_map[lyr], "lefdef_map NAME (label purpose)"
        elif lyr + ".LABEL" in lyt_map:
            layers[lyr], how[lyr] = lyt_map[lyr + ".LABEL"], "lyt lefdef layer-map LABEL purpose"
        elif lyr in map_draw:
            layers[lyr], how[lyr] = map_draw[lyr], ("drawing layer from lefdef_map "
                                                    "(no LABEL purpose declared)")
        elif lyr in lyt_map:
            layers[lyr], how[lyr] = lyt_map[lyr], ("drawing layer from lyt layer-map "
                                                   "(no LABEL purpose declared)")
        elif lyr in lyp_draw:
            layers[lyr], how[lyr] = lyp_draw[lyr], ("drawing layer from lyp "
                                                    "(no LABEL purpose declared)")
    return layers, how


def _streamout(params):
    if not shutil.which("klayout"):
        return _cde(objective="GDS streamout", status="failed",
                    error="klayout not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    def_file = params.get("def_file")
    top = params.get("top")
    tech_lef = params.get("tech_lef") or binding.get("tech_lef")
    cell_lefs = _as_list(params.get("cell_lef") or binding.get("cell_lef"))
    cell_gds = _as_list(params.get("cell_gds") or binding.get("cell_gds"))
    lyt = (params.get("tech_file") or binding.get("klayout_tech")
           or (binding.get("tech_file") if str(binding.get("tech_file") or "")
               .lower().endswith(".lyt") else None))
    lefdef_map = (params.get("lefdef_map") or params.get("lefdef_layer_map") or
                  binding.get("lefdef_map") or binding.get("klayout_lefdef_map"))
    if not lefdef_map and lyt:
        candidate = os.path.splitext(str(lyt))[0] + ".map"
        if os.path.exists(candidate):
            lefdef_map = candidate
    # DEF FILLS MUST LAND ON THE NODE'S DEDICATED FILL LAYER OR THEY DO NOT EXIST.
    # MEASURED, all on the same filled DEF (863 fill shapes):
    #   no map          -> fill INVENTED onto 8/28,10/28,12/28,14/28 (not sky130
    #                      layers at all); Magic: "Unknown layer/datatype ...
    #                      layer=8 type=28"; KLayout DRC sees no fill -> 0
    #   PDK map alone   -> "No mapping for layer 'met2', purpose 'FILL' - layer
    #                      is ignored" == ALL 863 SILENTLY DROPPED, warning only,
    #                      streamout still "succeeds"
    #   + FILL on the drawing layer  -> 69/20..72/20, but fill is FLOATING metal,
    #                      so the floating-metal rule fires once per shape
    #                      (m2.x 3 + m3.x 239 + m4.x 504 + m5.x 117 == 863) and
    #                      DRC goes 0 -> 971
    #   + FILL on the PDK fill layer -> 36/28,41/28,34/28,51/28,59/28  (correct)
    # THREE of those four are silent, which is why this is composed here rather
    # than left to the caller to remember.
    lefdef_map_source, fill_rows_added = ("caller_or_binding" if lefdef_map
                                          else "none"), []
    fill_map_reason = ""
    if lefdef_map and os.path.exists(str(lefdef_map)):
        magic_tech = (params.get("magic_tech") or binding.get("magic_tech") or
                      binding.get("magic_techfile"))
        augmented, fill_rows_added, fill_map_reason = _augment_map_with_fill(
            str(lefdef_map), magic_tech)
        if augmented:
            lefdef_map = augmented
            lefdef_map_source = "pdk_map_augmented_with_fill"
    # Fail closed: if the DEF carries fill that the EFFECTIVE map cannot place, the
    # streamout silently drops it (map without a FILL purpose) or invents a layer
    # for it (no map at all). A GDS missing its fill is not a lesser result, it is
    # a wrong one -- it under-reports density and mis-reports DRC.
    #
    # This interrogates the map that will actually be used rather than trusting
    # where it came from. An earlier version skipped the check whenever the caller
    # bound a map explicitly, on the theory that an explicit map is a deliberate
    # one. That is a fail-open, and it exempts the exact case most likely to be
    # wrong: binding the stock sky130A.map, which has no FILL purpose at all and
    # therefore drops every fill shape with only a warning.
    def_fills = 0
    try:
        mf = re.search(r"^\s*FILLS\s+(\d+)\s*;", open(str(def_file), encoding="utf-8",
                                                      errors="replace").read(), re.M)
        def_fills = int(mf.group(1)) if mf else 0
    except Exception:
        def_fills = 0
    if def_fills and not _map_has_fill_purpose(lefdef_map):
        why = (fill_map_reason or "no layer map bound") if not lefdef_map else (
            fill_map_reason or "bound layer map declares no FILL purpose")
        return _cde(objective="GDS streamout", status="failed", pdk_binding=binding or "none",
                    error=(f"DEF declares {def_fills} FILLS but the effective layer map "
                           f"cannot place them ({why}); streaming out would silently "
                           "drop or invent the fill"),
                    validation={"verdict": "fail"})
    for n, v in (("def_file", def_file), ("top", top), ("tech_lef", tech_lef)):
        if not v:
            return _cde(objective="GDS streamout", status="failed", pdk_binding=binding or "none",
                        error=f"missing required field '{n}'", validation={"verdict": "fail"})
    for p in [def_file, tech_lef] + cell_lefs + cell_gds + ([lefdef_map] if lefdef_map else []):
        if not os.path.exists(str(p)):
            return _cde(objective="GDS streamout", status="failed", pdk_binding=binding or "none",
                        error=f"input not found: {p}", validation={"verdict": "fail"})
    out_gds = os.path.join(_OUTPUT_DIR, f"{top}.gds")
    lef_list = json.dumps([tech_lef] + cell_lefs)
    gds_list = json.dumps(cell_gds)
    lyt_json = json.dumps(lyt) if (lyt and os.path.exists(str(lyt))) else "None"
    map_json = json.dumps(lefdef_map) if lefdef_map else "None"
    ok_txt = json.dumps(os.path.join(_OUTPUT_DIR, "streamout_ok.txt"))
    # --- PIN LABELS ---------------------------------------------------------
    # A GDS streamed from a DEF carries geometry but NO TEXT, so LVS must match
    # the layout to the schematic by graph isomorphism with nothing to anchor a
    # port to its name. Emit a text label at the centre of every top-level pin,
    # on the label layer THE PDK MAP DECLARES for that routing layer.
    _pins, _def_units = _bterm_pin_labels(def_file)
    _lyp = _resolve_lyp(params, binding, lyt)
    _label_layers, _label_layer_source = _resolve_label_layers(
        lefdef_map, lyt if (lyt and os.path.exists(str(lyt))) else None, _lyp,
        [p["layer"] for p in _pins])
    _labelled = [p for p in _pins if p["layer"] in _label_layers]
    _unlabelled = [p for p in _pins if p["layer"] not in _label_layers]
    # Labels are written in MICRONS (DText), not raw DEF units: the .lyt reader
    # may stream at a different dbu than the DEF (FreePDK45: DEF UNITS 2000 ->
    # 0.0005um, .lyt lefdef dbu 0.0001um), and integer DEF coordinates would land
    # every label 5x off its pin.
    _scale = (1.0 / _def_units) if _def_units else None
    _label_rows = [{"name": p["name"],
                    "x": (p["x"] * _scale) if _scale else p["x"],
                    "y": (p["y"] * _scale) if _scale else p["y"],
                    "layer": _label_layers[p["layer"]][0],
                    "datatype": _label_layers[p["layer"]][1]}
                   for p in _labelled]
    labels_json = json.dumps(_label_rows)
    microns_json = "True" if _scale else "False"
    # KLayout DEF import: apply the PDK .lyt technology (its lefdef layer-map maps
    # the routed DEF onto real sky130 GDS layer/datatype numbers), append the tech +
    # cell LEFs for cell abstracts, import the DEF, merge the standard-cell GDS for
    # real polygons, then write the final GDS. NOTE: a .lyt technology is applied via
    # pya.Technology().load(...).load_layout_options -- LEFDEFReaderConfiguration has
    # no load_lef_technology method.
    body = f"""import pya, json
LEFS = {lef_list}
GDS = {gds_list}
DEF_FILE = {json.dumps(def_file)}
OUT_GDS = {json.dumps(out_gds)}
TOP_NAME = {json.dumps(top)}
LYT = {lyt_json}
LEFDEF_MAP = {map_json}
PIN_LABELS = {labels_json}
LABELS_IN_MICRONS = {microns_json}
ly = pya.Layout()
opt2 = pya.LoadLayoutOptions()
# An explicit LEF/DEF .map is the AUTHORITATIVE routed-layer mapping and must win.
# Deriving reader options from a .lyt technology (tech.load_layout_options) pulls
# in the .lyt's embedded LEF/DEF reader configuration, which -- even when map_file
# is set afterward -- mis-assigns DEF NET/SPNET routing (empirically shifts met1
# routing off L68, met2 off L69, etc.: e.g. myTop2 met2 collapsed 861->72 um2 and
# reappeared on met4/met5). Streaming from a plain LoadLayoutOptions() + map_file
# reproduces the faithful geometry (verified layer-for-layer against an independent
# magic streamout). Only fall back to the .lyt path when NO .map is available.
if LYT and not LEFDEF_MAP:
    try:
        tech = pya.Technology()
        tech.load(LYT)
        opt2 = tech.load_layout_options
        print("streamout: applied .lyt layer-map from", LYT)
    except Exception as e:
        print("streamout: .lyt technology load failed, bare LEF/DEF fallback:", e)
elif LYT:
    print("streamout: .map present; using plain LoadLayoutOptions (map_file is authoritative), skipping .lyt reader config from", LYT)
try:
    cfg = opt2.lefdef_config
    if LEFDEF_MAP:
        cfg.map_file = LEFDEF_MAP
        print("streamout: applied LEF/DEF layer map", LEFDEF_MAP)
    # KLayout API quirk: cfg.lef_files returns a FRESH copy on every access, so
    # cfg.lef_files.append(x) mutates a throwaway and the LEFs are never loaded
    # (symptom: "Macro not found in LEF file" for every cell, and DEF NET/SPNET
    # routing mis-assigned by +3 metal layers because the reader falls back to an
    # ordinal layer scheme instead of the map's by-name mapping). Assign the whole
    # list at once so it actually takes effect.
    existing = list(cfg.lef_files)
    cfg.lef_files = existing + [l for l in LEFS if l not in existing]
    # Resolve standard-cell macros directly from the cell GDS so the DEF reader
    # instantiates each placed cell's REAL geometry (li/met/poly/...) by name.
    # This is MUTUALLY EXCLUSIVE with a post-hoc `ly.read(cell_gds)` merge: doing
    # both draws every cell's li twice -- the LEF/DEF reader's macro geometry AND
    # the merged real-GDS li, mutually offset ~60-165nm -- which manufactures
    # thousands of phantom li.3 (min li spacing 0.17um) violations INSIDE
    # otherwise-DRC-clean library cells (empirically 5128 on myTop2, ~479 of them
    # attributed to cell interiors that are clean in isolation). macro_resolution_mode
    # = 2 uses macro_layout_files where the macro is found and falls back to LEF
    # geometry only for macros absent from the GDS (e.g. DEF fixed-via cells), so
    # there is exactly ONE copy of every cell's geometry.
    if GDS:
        cfg.macro_resolution_mode = 2
        cfg.macro_layout_files = GDS
        print("streamout: macro_resolution_mode=2, macros resolved from", GDS)
    # Ask the DEF reader for pin labels/pin names too (the explicit PIN_LABELS
    # below are the gated, verified source; these are belt-and-braces).
    for _opt in ("produce_labels", "produce_pin_names"):
        try:
            setattr(cfg, _opt, True)
            print("streamout: lefdef_config.%s = True" % _opt)
        except Exception as _e:
            print("streamout: lefdef_config.%s unsupported:" % _opt, _e)
    opt2.lefdef_config = cfg
except Exception as e:
    print("streamout: lef config failed:", e)
ly.read(DEF_FILE, opt2)
# Cell geometry is resolved from macro_layout_files during the DEF read above, so
# it must NOT be merged again here (that is what caused the li double-draw). Only
# fall back to an explicit merge if no cell GDS was configured for macro resolution.
if not GDS:
    pass
# Merging the full cell-library GDS pulls in every library cell as an extra top
# cell; a DRC deck's `source.top_cell` then fails with "multiple top cells".
# Reduce to exactly the target hierarchy: keep TOP_NAME + all cells it calls.
tc = ly.cell(TOP_NAME) if TOP_NAME else None
if tc is not None:
    keep = set(tc.called_cells())
    keep.add(tc.cell_index())
    drop = [c.cell_index() for c in ly.each_cell() if c.cell_index() not in keep]
    if drop:
        ly.delete_cells(drop)
        print("streamout: pruned", len(drop), "cells; single top", TOP_NAME)
# PIN LABELS: a text at the centre of each top-level pin, on the label layer
# resolved from the PDK map/.lyt/.lyp. Written AFTER the cell prune so the labels
# land in the surviving top cell. Coordinates are microns (DText) when the DEF
# UNITS were known, so they are independent of the reader dbu.
_written = 0
if PIN_LABELS and tc is not None:
    for _p in PIN_LABELS:
        _li = ly.layer(_p["layer"], _p["datatype"])
        if LABELS_IN_MICRONS:
            tc.shapes(_li).insert(pya.DText(_p["name"], pya.DTrans(_p["x"], _p["y"])))
        else:
            tc.shapes(_li).insert(pya.Text(_p["name"], pya.Trans(int(_p["x"]), int(_p["y"]))))
        _written += 1
    print("streamout: wrote", _written, "pin label(s)")
ly.write(OUT_GDS)
# VERIFY from the written file, not from intent: a port counts as labelled only
# if the streamed top cell carries a text with its name on its label layer.
_verified = []
try:
    _chk = pya.Layout()
    _chk.read(OUT_GDS)
    _ct = _chk.cell(TOP_NAME) if TOP_NAME else None
    _texts = {{}}
    if _ct is not None:
        for _li in _chk.layer_indexes():
            _inf = _chk.get_info(_li)
            for _s in _ct.shapes(_li).each():
                if _s.is_text():
                    _texts.setdefault(_s.text_string, set()).add((_inf.layer, _inf.datatype))
    _verified = [p["name"] for p in PIN_LABELS
                 if (p["layer"], p["datatype"]) in _texts.get(p["name"], set())]
except Exception as _e:
    print("streamout: label verification failed:", _e)
print("__PORTS_LABELLED__ " + json.dumps(_verified))
open({ok_txt}, "w").write("ok")
"""
    t0 = time.time()
    proc, out = _run_klayout_script(body, "streamout")
    elapsed = time.time() - t0
    if not os.path.exists(out_gds):
        return _cde(objective=f"GDS streamout of {top}", status="failed",
                    pdk_binding=binding or "none",
                    error="KLayout DEF->GDS streamout produced no GDS; see streamout.log:\n"
                          + out[-1500:], validation={"verdict": "fail"},
                    provenance={"klayout": _klayout_version(), "log": "streamout.log"})
    stats = _gds_stats(out_gds, want_top=top)
    size = os.path.getsize(out_gds)
    top_cell = top if stats.get("has_top") else (stats.get("top") or top)
    # PIN-LABEL GATE. A tapeout GDS whose ports carry no text forces LVS to match
    # by graph isomorphism alone. That is not a smaller check -- on a symmetric
    # block it can succeed with the ports permuted, which is a pass that means
    # the opposite of what it says.
    _n_labels = stats.get("labels")
    _mv = re.search(r"__PORTS_LABELLED__ (\[.*\])", out)
    try:
        _verified = set(json.loads(_mv.group(1))) if _mv else None
    except ValueError:
        _verified = None
    _port_names = {p["name"] for p in _pins}
    _n_verified = len(_verified & _port_names) if _verified is not None else 0
    _drawing_fallback = sorted(k for k, v in _label_layer_source.items()
                               if "no LABEL purpose" in v)
    if _pins and _unlabelled:
        _label_verdict = "review"
        _label_note = (
            "final GDSII written, but %d of %d top-level port(s) could not be "
            "labelled because neither the layer map, the .lyt nor the .lyp "
            "declares a LABEL purpose or drawing layer for their routing layer "
            "(%s). LVS on this GDS cannot match those ports by name."
            % (len(_unlabelled), len(_pins),
               ", ".join(sorted({p["layer"] for p in _unlabelled}))))
    elif _pins and _verified is None:
        _label_verdict = "review"
        _label_note = ("final GDSII written, but the post-write label verification "
                       "did not report (__PORTS_LABELLED__ missing); port labelling "
                       "is UNVERIFIED")
    elif _pins and _n_verified < len(_port_names):
        _label_verdict = "review"
        _label_note = (
            "final GDSII written, but only %d of %d top-level port(s) carry a text "
            "label on their label layer in the streamed GDS (verified by re-reading "
            "it); LVS cannot match the rest by name" % (_n_verified, len(_port_names)))
    elif _pins and not _n_labels:
        _label_verdict = "review"
        _label_note = (
            "final GDSII written, but it carries NO text labels while the DEF "
            "declares %d top-level port(s); LVS would have to match by graph "
            "isomorphism alone" % len(_pins))
    elif not _pins:
        _label_verdict = "review"
        _label_note = ("final GDSII written, but no PINS section could be read "
                       "from the DEF, so port labelling was NOT assessed")
    else:
        _label_verdict = "pass"
        _label_note = ("final GDSII written with %d/%d named top-level port label(s) "
                       "verified on the streamed GDS; LVS can match ports by name"
                       % (_n_verified, len(_port_names)))
        if _drawing_fallback:
            _label_verdict = "pass_with_caveats"
            _label_note += ("; the PDK declares no LABEL purpose for %s, so those "
                            "labels are on the pin's drawing layer"
                            % ", ".join(_drawing_fallback))

    # DROPPED GEOMETRY IS A FAILURE, NOT A WARNING.
    # KLayout reports an unmapped LEF/DEF purpose as
    #     "No mapping for layer 'met2', purpose 'FILL' - layer is ignored"
    # on STDOUT and carries on: the GDS is written, the exit code is 0, and the
    # dropped shapes are simply absent. MEASURED: binding the vendor sky130A.map
    # (which has no FILL purpose) silently discarded all 863 metal-fill shapes
    # while still reporting a successful streamout. Geometry that the tapeout
    # deliverable is supposed to carry must never go missing quietly, so any
    # ignored layer fails the stage and NAMES what was dropped.
    _ignored = re.findall(
        r"No mapping for layer '([^']+)', purpose '([^']+)' - layer is ignored", out)
    if _ignored:
        _uniq = sorted({"%s.%s" % (a, b) for a, b in _ignored})
        return _cde(
            objective=f"GDS streamout of {top}", status="failed",
            pdk_binding=binding or "none",
            error=("STREAMOUT DROPPED GEOMETRY: the LEF/DEF layer map has no "
                   "entry for %s, so KLayout IGNORED those shapes and wrote a "
                   "GDS without them. This is silent data loss in the tapeout "
                   "deliverable -- fill placed to satisfy density rules would "
                   "be absent while the stage reported success. Add the missing "
                   "purpose(s) to the layer map (fill belongs on the metal "
                   "DRAWING layer so it counts toward density)."
                   % ", ".join(_uniq)),
            signoff={"dropped_purposes": _uniq,
                     "lefdef_map": os.path.basename(str(lefdef_map)) if lefdef_map else None,
                     "lefdef_map_source": lefdef_map_source,
                     "assessed": False},
            validation={"verdict": "fail",
                        "note": "layer map incomplete; geometry discarded"},
            provenance={"klayout": _klayout_version(), "log": "streamout.log"})

    return _cde(
        objective=f"GDS streamout of {top}", status="completed",
        pdk_binding=binding or "none",
        results={"gds": {"value": f"{top}.gds", "unit": "-"},
                 "gds_bytes": {"value": size, "unit": "bytes"},
                 "layers": {"value": stats.get("layers"), "unit": "count"},
                 "pin_labels": {"value": stats.get("labels"), "unit": "count",
                                "class": "gating",
                                "basis": "klayout_text_count_on_streamed_gds",
                                "closes_at": "> 0 when the design has ports",
                                "note": ("Named ports are what let LVS match by "
                                         "NAME. Without them LVS falls back to "
                                         "graph isomorphism, which on a symmetric "
                                         "block can match with the ports "
                                         "permuted.")}},
        qor={"gds_bytes": size, "cells": stats.get("cells"),
             "pin_labels": stats.get("labels"),
             "ports_in_def": len(_pins),
             "ports_labelled": _n_verified,
             "ports_labelled_pct": (round(100.0 * _n_verified / len(_port_names), 2)
                                    if _port_names else None),
             "ports_label_written": len(_labelled),
             "ports_unlabelled": len(_port_names) - _n_verified},
        signoff={"gds": f"{top}.gds", "top_cell": top_cell,
                 "cells": stats.get("cells"), "layers": stats.get("layers"),
                 "pin_labels": stats.get("labels"),
                 "ports_in_def": len(_pins),
                 "ports_labelled_verified": _n_verified,
                 "ports_labelled": sorted(_verified & _port_names)[:64]
                 if _verified is not None else [],
                 "ports_unlabelled": [
                     {"port": p["name"], "layer": p["layer"],
                      "reason": ("no LABEL purpose or drawing layer for this "
                                 "routing layer in the map/.lyt/.lyp"
                                 if p["layer"] not in _label_layers else
                                 "label written but not found on the streamed GDS")}
                     for p in _pins
                     if _verified is None or p["name"] not in _verified][:32],
                 "label_layers": {k: list(v) for k, v in _label_layers.items()} or None,
                 "label_layer_source": _label_layer_source or None,
                 "label_on_drawing_layer": _drawing_fallback or None,
                 "label_coordinates": ("microns from DEF UNITS %s" % _def_units
                                       if _def_units else "raw DEF units (no UNITS)"),
                 "layer_props": os.path.basename(str(_lyp)) if _lyp else None,
                 "lefdef_map": os.path.basename(str(lefdef_map)) if lefdef_map else None,
                 "lefdef_map_source": lefdef_map_source,
                 "fill_purpose_rows_added": fill_rows_added or None,
                 "stream_complete_note": (
                     "pin_labels is the text-label count on the streamed GDS; "
                     "a design with top-level ports but pin_labels==0 is a "
                     "pin-labeling gap (named pins required for name-matched LVS), "
                     "not a clean streamout"),
                 "report": "streamout.log"},
        inputs_ref={"def_file": def_file, "tech_lef": tech_lef,
                    "cell_lef": cell_lefs, "cell_gds": cell_gds,
                    "lefdef_map": lefdef_map},
        assumptions=["final GDSII streamed from the routed/filled DEF + cell GDS; "
                     "run DRC/LVS on the final GDS before tapeout",
                     "pin labels are placed at the centre of each DEF PIN "
                     "rectangle on the label layer resolved from the PDK .map NAME "
                     "row, else the .lyt LEF/DEF `<layer>.LABEL` mapping, else the "
                     "pin's drawing layer (recorded in label_layer_source); "
                     "ports_labelled counts only labels verified on the written GDS"],
        validation={"verdict": _label_verdict, "note": _label_note},
        provenance={"klayout": _klayout_version(), "runtime_s": round(elapsed, 3),
                    "log": "streamout.log"},
    )


def _merge(params):
    if not shutil.which("klayout"):
        return _cde(objective="GDS merge", status="failed",
                    error="klayout not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    gds_files = _as_list(params.get("gds_files"))
    top = params.get("top", "merged")
    # SEAL RING. A tapeout-ready reticle field is the core GDS plus a seal ring
    # (and, on most nodes, the scribe/crack-stop structures that come with it)
    # merged around it. The seal ring arrives from the foundry as a fixed GDS --
    # it is never synthesized, and it is never DRC-clean against the core's own
    # rules, which is why it is merged at the very end rather than placed as a
    # macro. Modeled as an ADDITIONAL merge input (ORFS `SEAL_GDS`) so it flows
    # through the same collision and stats checks as everything else.
    seal_gds = params.get("seal_gds")
    if seal_gds:
        if not os.path.exists(str(seal_gds)):
            return _cde(objective="GDS merge", status="failed",
                        pdk_binding=binding or "none",
                        error=f"seal_gds not found: {seal_gds}",
                        validation={"verdict": "fail"})
        gds_files = list(gds_files) + [seal_gds]
    if not gds_files:
        return _cde(objective="GDS merge", status="failed", pdk_binding=binding or "none",
                    error="missing required 'gds_files'", validation={"verdict": "fail"})
    for p in gds_files:
        if not os.path.exists(str(p)):
            return _cde(objective="GDS merge", status="failed", pdk_binding=binding or "none",
                        error=f"input not found: {p}", validation={"verdict": "fail"})
    out_gds = os.path.join(_OUTPUT_DIR, f"{top}.gds")
    gds_list = json.dumps(gds_files)
    body = f"""import pya, json
ly = pya.Layout()
for g in {gds_list}:
    ly.read(g)
ly.write({json.dumps(out_gds)})
"""
    t0 = time.time()
    proc, out = _run_klayout_script(body, "merge")
    elapsed = time.time() - t0
    if not os.path.exists(out_gds):
        return _cde(objective=f"GDS merge -> {top}", status="failed", pdk_binding=binding or "none",
                    error="KLayout GDS merge produced no GDS; see merge.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"klayout": _klayout_version(), "log": "merge.log"})
    stats = _gds_stats(out_gds)
    size = os.path.getsize(out_gds)
    return _cde(
        objective=f"GDS merge of {len(gds_files)} file(s) -> {top}", status="completed",
        pdk_binding=binding or "none",
        results={"gds": {"value": f"{top}.gds", "unit": "-"},
                 "gds_bytes": {"value": size, "unit": "bytes"}},
        qor={"gds_bytes": size, "cells": stats.get("cells")},
        signoff={"gds": f"{top}.gds", "merged_files": [os.path.basename(str(g)) for g in gds_files],
                 "cells": stats.get("cells"), "report": "merge.log",
                 "seal_ring": (os.path.basename(str(seal_gds)) if seal_gds else None),
                 "seal_ring_note": (
                     "seal ring merged as fixed foundry GDS; it is NOT DRC-clean "
                     "against core rules and must be waived/excluded in the DRC "
                     "deck per the foundry's seal-ring instructions"
                     if seal_gds else None)},
        inputs_ref={"gds_files": gds_files},
        assumptions=["flat merge of the supplied GDS; resolve any cell-name collisions upstream"],
        validation={"verdict": "pass", "note": "merged GDSII written"},
        provenance={"klayout": _klayout_version(), "runtime_s": round(elapsed, 3),
                    "log": "merge.log"},
    )


def _write_cdl(params):
    """Emit the CDL netlist -- a foundry TAPEOUT DELIVERABLE, not a report.

    CDL (Circuit Description Language) is the flat, SPICE-like netlist the foundry
    runs its own independent LVS against. Handing over a GDS without one means the
    foundry cannot verify that the shipped layout matches the intended circuit,
    which is a hard stop at most tapeout desks. ORFS emits it in the `final` stage
    (`CDL_FILE` / `write_cdl -masters`).

    Lives with GDS assembly because that is where the tapeout PACKAGE is built:
    GDS, CDL and the seal ring are the same deliverable set with the same
    lifetime, so one agent owns the handoff bundle.

    `masters` (the PDK's cell-level CDL) is REQUIRED: without it OpenROAD emits
    subcircuit CALLS with no matching definitions, so the netlist reads as
    complete but every standard cell is an undefined black box -- a file that
    LOOKS like a deliverable and fails the foundry's LVS.
    """
    if not shutil.which("openroad"):
        return _cde(objective="CDL netlist", status="failed",
                    error="openroad not found on PATH", validation={"verdict": "fail"})
    binding = params.get("pdk_binding") or {}
    def_file = params.get("def_file") or params.get("odb_file")
    tech_lef = params.get("tech_lef") or binding.get("tech_lef")
    cell_lefs = _as_list(params.get("cell_lef") or binding.get("cell_lef"))
    masters = _as_list(params.get("masters") or params.get("cdl_masters")
                       or binding.get("cdl_masters"))
    top = params.get("top", "design")
    if not def_file:
        return _cde(objective="CDL netlist", status="failed",
                    pdk_binding=binding or "none",
                    error="missing required field 'def_file' (or 'odb_file')",
                    validation={"verdict": "fail"})
    if not masters:
        return _cde(
            objective="CDL netlist", status="failed", pdk_binding=binding or "none",
            error=("missing required field 'masters' -- the PDK cell CDL "
                   "(e.g. sky130_fd_sc_hd.cdl). Without it every standard cell is "
                   "an UNDEFINED subcircuit: the emitted netlist looks complete "
                   "but fails the foundry's LVS, which is the exact failure this "
                   "deliverable exists to prevent."),
            validation={"verdict": "fail"})
    for p in [def_file] + ([tech_lef] if tech_lef else []) + cell_lefs + masters:
        if not os.path.exists(str(p)):
            return _cde(objective="CDL netlist", status="failed",
                        pdk_binding=binding or "none",
                        error=f"input not found: {p}", validation={"verdict": "fail"})

    out_cdl = os.path.join(_OUTPUT_DIR, f"{top}.cdl")
    is_odb = str(def_file).endswith(".odb")
    if is_odb:
        reads = f"read_db {{{def_file}}}"
    else:
        if not tech_lef:
            return _cde(objective="CDL netlist", status="failed",
                        pdk_binding=binding or "none",
                        error="DEF input requires 'tech_lef'",
                        validation={"verdict": "fail"})
        reads = "\n".join([f"read_lef {{{tech_lef}}}"]
                          + [f"read_lef {{{c}}}" for c in cell_lefs]
                          + [f"read_def {{{def_file}}}"])
    fillers = (" -include_fillers"
               if str(params.get("include_fillers", "")).lower() in ("1", "true", "yes")
               else "")
    masters_arg = " ".join(str(m) for m in masters)
    script = f"""{reads}
write_cdl -masters {{{masters_arg}}}{fillers} {{{out_cdl}}}
exit
"""
    sp = os.path.join(_OUTPUT_DIR, "write_cdl.tcl")
    open(sp, "w").write(script)
    t0 = time.time()
    _save_run_command(["openroad", "-exit", sp])
    proc = subprocess.run(["openroad", "-exit", sp], capture_output=True,
                          text=True, cwd=_WORK_DIR)
    elapsed = time.time() - t0
    out = proc.stdout + "\n" + proc.stderr
    open(os.path.join(_OUTPUT_DIR, "write_cdl.log"), "w").write(out)
    if proc.returncode != 0 or not os.path.exists(out_cdl):
        return _cde(objective="CDL netlist", status="failed",
                    pdk_binding=binding or "none",
                    inputs_ref={"def_file": def_file, "masters": masters},
                    error="OpenROAD write_cdl failed; see write_cdl.log:\n" + out[-1500:],
                    validation={"verdict": "fail"},
                    provenance={"openroad": "openroad", "log": "write_cdl.log"})

    text = open(out_cdl, encoding="utf-8", errors="replace").read()
    subckts = len(re.findall(r"^\.SUBCKT\s", text, re.M | re.I))
    instances = len(re.findall(r"^X", text, re.M))
    size = os.path.getsize(out_cdl)
    # An empty or instance-free CDL is not a deliverable. Catch it here rather
    # than letting the foundry find it.
    usable = size > 0 and instances > 0
    return _cde(
        objective=f"CDL netlist for {top} (foundry LVS deliverable)",
        status="completed" if usable else "failed",
        pdk_binding=binding or "none",
        results={"cdl": {"value": f"{top}.cdl", "unit": "-"},
                 "cdl_instances": {"value": instances, "unit": "count"}},
        qor={"cdl_bytes": size, "cdl_subckts": subckts, "cdl_instances": instances},
        signoff={"cdl": f"{top}.cdl", "masters": [os.path.basename(str(m)) for m in masters],
                 "include_fillers": bool(fillers), "report": "write_cdl.log",
                 "purpose": "foundry-side independent LVS against the shipped GDS"},
        inputs_ref={"def_file": def_file, "tech_lef": tech_lef,
                    "cell_lef": cell_lefs, "masters": masters},
        assumptions=["cell-level subcircuits come from the supplied PDK CDL masters; "
                     "this tool never synthesizes a device-level model"],
        validation={"verdict": "pass" if usable else "fail",
                    "note": ("CDL written: %d instance(s), %d subckt definition(s)"
                             % (instances, subckts)) if usable else
                    ("write_cdl produced a netlist with %d instances (%d bytes) -- "
                     "an empty CDL is not a deliverable" % (instances, size))},
        provenance={"openroad": "openroad", "runtime_s": round(elapsed, 3),
                    "log": "write_cdl.log"},
    )


def dispatch(params):
    s = params.get("scenario")
    if s in ("streamout", "gds_streamout", "assemble"):
        return _streamout(params)
    if s in ("merge", "gds_merge"):
        return _merge(params)
    if s in ("write_cdl", "cdl", "cdl_netlist"):
        return _write_cdl(params)
    return _cde(objective="GDS assembly", status="failed",
                error=f"unknown scenario '{s}'; supported: streamout, merge, write_cdl",
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
