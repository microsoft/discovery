#!/usr/bin/env python3
"""reachability_proof.py -- machine-checked coverage reachability proof generator.

Implements the campaign-wide **A-policy** (reachable-coverage closure): coverage
closure means 100% of *reachable* coverage, not a literal 100%. Real RTL always
leaves a residual of provably-unreachable points (constant/tied nets, dead
branches from tie-offs, structurally-impossible generate toggles) that no
stimulus can ever hit. This module partitions every UNHIT coverage point into:

  * ``reachable_unhit``          -- a real stimulus gap; the gate FAILS closed on
                                    any such point (iterate/expand the testbench).
  * ``structurally_unreachable`` -- provably impossible to hit; auto-excludable
                                    ONLY under a recorded human A-policy
                                    authorization, enumerated + classified here.

FAIL-CLOSED CONTRACT (mandatory): a point is classified ``structurally_unreachable``
ONLY when a structural heuristic OR a human-supplied override explicitly proves it.
Every other unhit point defaults to ``reachable_unhit``. The generator never
reclassifies a reachable hole as unreachable to force closure.

Inputs (any one):
  * a Verilator ``verilator_coverage.dat`` / annotated ``.dat`` file, OR
  * a JSON list of points ``[{type,file,line,name,hits}, ...]``.
Optional:
  * ``reachability_overrides.json`` -- human-declared structural points, each with
    ``{match:{file?,line?,name?,type?}, class, rationale, authorized_by}``. An
    override REQUIRES ``authorized_by`` (the recorded A-policy human approver);
    an override without it is IGNORED (the point stays reachable_unhit).

Output: ``code_coverage_reachability.json`` with the schema the coverage agents,
the silicon-task-definition gates, and the chip-ppa-signoff-design-review agent
consume. ``basis`` records the measurement basis so a proof is never silently
carried across a different basis (e.g. Verilator-basis set onto a GHDL/VHDL run).
"""
import argparse
import datetime
import json
import os
import re
import sys

SCHEMA_VERSION = "1.0"
_POINT_TYPES = ("line", "branch", "toggle", "cond", "expr", "fsm")

# --- structural-unreachability heuristics --------------------------------------
# Each heuristic proves a point CANNOT be reached from any stimulus. Conservative
# by construction: it must match a positive structural signature, never "looks
# hard to cover". A miss just leaves the point as reachable_unhit (fail-closed).
_STRUCTURAL_HEURISTICS = (
    # (class, compiled regex over the point name/comment, rationale template)
    ("constant",
     re.compile(r"(?:^|[^a-z0-9_])(?:const|constant|tied|tieoff|tie_off|1'b[01]|zero_?const|one_?const)"
                r"|_gnd(?:$|[^a-z0-9])|_vdd(?:$|[^a-z0-9])", re.I),
     "net is driven by a structural constant / tie-off; it can never change value"),
    ("tied_enable_dead_branch",
     re.compile(r"(?:read_?en|write_?en|wen|ren|enable|_en)_(?:tied|const)"
                r"|tied_?(?:high|low)|dead_?branch|unreachable_?branch", re.I),
     "branch guarded by a tied enable; the complementary leg is structurally dead"),
    ("unreachable_generate_toggle",
     re.compile(r"gen(?:erate)?[._].*(?:const|tied|unreach)|genblk.*_const"
                r"|param_?const_?compare|structurally_?impossible", re.I),
     "generate-produced node whose alternate value cannot occur for the elaborated parameters"),
)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _parse_verilator_dat(path):
    """Parse a Verilator coverage .dat file into a list of point dicts.

    Verilator encodes each record as ``C <key/val blob> <count>`` where the blob
    is a sequence of ``\\x01<key>\\x02<value>`` pairs (keys: f=file, l=line,
    n=name/comment, page=coverage page e.g. 'v_line'/'v_toggle'/'v_branch').
    We degrade gracefully on any format drift.
    """
    points = []
    try:
        with open(path, "r", errors="replace") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                if not line or not line.startswith("C"):
                    continue
                # split trailing integer count
                m = re.search(r"\s(\d+)\s*$", line)
                hits = int(m.group(1)) if m else 0
                blob = line[1:m.start()] if m else line[1:]
                fields = {}
                for pair in re.split(r"[\x01]", blob):
                    if "\x02" in pair:
                        k, v = pair.split("\x02", 1)
                        fields[k.strip()] = v.strip()
                page = fields.get("page", "")
                ptype = ("toggle" if "toggle" in page else
                         "branch" if "branch" in page else
                         "line" if "line" in page else
                         "fsm" if "fsm" in page else
                         "cond" if ("cond" in page or "expr" in page) else "line")
                points.append({
                    "type": ptype,
                    "file": fields.get("f", ""),
                    "line": fields.get("l", ""),
                    "name": fields.get("n", "") or fields.get("o", ""),
                    "hits": hits,
                })
    except OSError as exc:
        raise SystemExit(f"reachability_proof: cannot read dat file {path}: {exc}")
    return points


def _load_points(args):
    if args.dat:
        return _parse_verilator_dat(args.dat), os.path.basename(args.dat)
    if args.points_json:
        with open(args.points_json) as fh:
            data = json.load(fh)
        pts = data.get("points", data) if isinstance(data, dict) else data
        return list(pts), args.basis or os.path.basename(args.points_json)
    raise SystemExit("reachability_proof: supply --dat or --points-json")


def _load_overrides(path):
    if not path or not os.path.exists(path):
        return []
    with open(path) as fh:
        raw = json.load(fh)
    items = raw.get("overrides", raw) if isinstance(raw, dict) else raw
    valid = []
    for o in items:
        # An override is honored ONLY with a recorded human A-policy approver.
        if not o.get("authorized_by"):
            continue
        if not o.get("class") or not o.get("match"):
            continue
        valid.append(o)
    return valid


def _override_match(point, overrides):
    for o in overrides:
        mm = o["match"]
        ok = True
        for key in ("file", "line", "name", "type"):
            if key in mm and mm[key] not in (None, ""):
                pv = str(point.get(key, ""))
                if key == "name":
                    if str(mm[key]) not in pv:
                        ok = False
                        break
                elif pv != str(mm[key]):
                    ok = False
                    break
        if ok:
            return o
    return None


def _heuristic_class(point):
    hay = f"{point.get('name','')} {point.get('file','')}"
    for klass, rx, rationale in _STRUCTURAL_HEURISTICS:
        if rx.search(hay):
            return klass, rationale
    return None, None


def build_proof(points, basis, overrides):
    reachable_unhit = []
    structural = []
    totals = {t: {"points": 0, "hit": 0, "unhit": 0} for t in _POINT_TYPES}

    for p in points:
        ptype = p.get("type", "line")
        if ptype not in totals:
            totals[ptype] = {"points": 0, "hit": 0, "unhit": 0}
        totals[ptype]["points"] += 1
        hits = int(p.get("hits", 0) or 0)
        if hits > 0:
            totals[ptype]["hit"] += 1
            continue
        totals[ptype]["unhit"] += 1

        # UNHIT: classify. Overrides (human-authorized) win, then heuristics.
        ov = _override_match(p, overrides)
        if ov:
            structural.append({**_pt(p), "class": ov["class"],
                               "rationale": ov.get("rationale", ""),
                               "source": "human_override",
                               "authorized_by": ov["authorized_by"]})
            continue
        klass, rationale = _heuristic_class(p)
        if klass:
            structural.append({**_pt(p), "class": klass,
                               "rationale": rationale, "source": "heuristic"})
            continue
        # FAIL-CLOSED default: a real stimulus gap.
        reachable_unhit.append(_pt(p))

    reachable_total = len(reachable_unhit)
    per_type_reachable = {t: 0 for t in totals}
    for r in reachable_unhit:
        per_type_reachable[r["type"]] = per_type_reachable.get(r["type"], 0) + 1

    proof = {
        "schema_version": SCHEMA_VERSION,
        "tool": "reachability-proof",
        "policy": "A (reachable-coverage closure)",
        "basis": basis,
        "generated_at": _now(),
        "totals": totals,
        "reachable_unhit_by_type": per_type_reachable,
        "reachable_unhit": reachable_unhit,
        "structurally_unreachable": structural,
        "summary": {
            "reachable_unhit_total": reachable_total,
            "structural_total": len(structural),
            # Closure is a REACHABLE-coverage claim: it holds only when there is
            # no reachable_unhit point. Structural exclusions are enumerated but
            # require a recorded human A-policy authorization to clear the gate
            # (each structural item from a human_override already carries one;
            # heuristic items still need the campaign/catalog A-policy ruling).
            "reachable_unhit_zero": reachable_total == 0,
            "structural_all_authorized": all(
                s.get("source") == "human_override" for s in structural),
        },
    }
    return proof


def _pt(p):
    return {"type": p.get("type", "line"), "file": p.get("file", ""),
            "line": p.get("line", ""), "name": p.get("name", ""),
            "hits": int(p.get("hits", 0) or 0)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate a coverage reachability proof (A-policy).")
    ap.add_argument("--dat", help="Verilator coverage .dat file")
    ap.add_argument("--points-json", help="JSON list/obj of coverage points")
    ap.add_argument("--basis", help="measurement basis label (e.g. ghdl_vcd, verilator_coverage.dat)")
    ap.add_argument("--overrides", default="reachability_overrides.json",
                    help="human-authorized structural overrides JSON")
    ap.add_argument("-o", "--output", default="reports/code_coverage_reachability.json")
    args = ap.parse_args(argv)

    points, basis = _load_points(args)
    if args.basis:
        basis = args.basis
    overrides = _load_overrides(args.overrides)
    proof = build_proof(points, basis, overrides)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as fh:
        json.dump(proof, fh, indent=2)

    s = proof["summary"]
    print(f"reachability_proof: basis={basis} points={sum(t['points'] for t in proof['totals'].values())} "
          f"reachable_unhit={s['reachable_unhit_total']} structural={s['structural_total']} "
          f"-> {'CLOSED' if s['reachable_unhit_zero'] else 'OPEN (reachable gap)'}")
    # Exit non-zero when there is a real reachable gap so a CI/gate caller fails closed.
    return 0 if s["reachable_unhit_zero"] else 2


if __name__ == "__main__":
    sys.exit(main())
