"""Structural reset-hygiene analysis from the elaborated Yosys netlist.

WHY THIS EXISTS
---------------
The RTL-design tool checked inferred latches and driver problems but had NO
reset hygiene checks at all -- nothing looked at sync vs async, polarity,
reset-as-data, or whether an async reset's DE-assertion is synchronized. Reset
bugs are among the most expensive defects in a design because they are
intermittent, they survive most functional simulation (which usually applies a
clean reset once, at time zero), and they surface on silicon as a rare
failure-to-start.

WHY STRUCTURAL AND NOT REGEX
----------------------------
The sibling `cdc_scan` path in this tool infers clock domains by regex over the
RAW SOURCE TEXT and then forms a cartesian product of clock names, which both
over- and under-reports. That is the method trap to avoid: when an elaborated
netlist is available, use it. Yosys encodes reset structure directly in the
flop cell TYPE and its PARAMETERS -- `$adff` carries an async reset with an
`ARST_POLARITY`, `$sdff` carries a synchronous one -- so async/sync and polarity
are read as facts about the design rather than guessed from spelling.

WHAT REMAINS A HEURISTIC, AND IS LABELLED AS ONE
------------------------------------------------
Two findings here are naming-convention checks (`rst_n` used active-high) and
one is a topology heuristic (an async reset arriving straight from a port with
no synchronizer). Those cannot be proven from structure alone, so each is
emitted as `advisory` with its basis recorded, and only the structurally
provable findings gate.
"""

import json
import re

# Yosys flop cell types and where their reset lives. After `proc; opt`, a
# register with an asynchronous reset becomes $adff/$adffe; a synchronous one
# becomes $sdff/$sdffe. $dffsr carries independent set and reset.
_ASYNC_FF = {"$adff": "ARST", "$adffe": "ARST", "$adlatch": "ARST",
             "$aldff": "ALOAD", "$aldffe": "ALOAD"}
_SYNC_FF = {"$sdff": "SRST", "$sdffe": "SRST", "$sdffce": "SRST"}
_SR_FF = {"$dffsr": "CLR", "$dffsre": "CLR"}
_NO_RESET_FF = {"$dff", "$dffe", "$ff"}

_ACTIVE_LOW_NAME = re.compile(r"(_n$|_n\[|^n_|_ni$|_neg$|resetn|rstn|_b$)", re.I)
_RESETish = re.compile(r"rst|reset|clr|clear", re.I)


class NetlistUnavailable(Exception):
    """Raised when the JSON netlist cannot be read. Never becomes 'clean'."""


def load(path_or_text):
    """Parse a Yosys `write_json` netlist."""
    try:
        if isinstance(path_or_text, str) and path_or_text.lstrip()[:1] == "{":
            return json.loads(path_or_text)
        with open(path_or_text) as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        raise NetlistUnavailable("could not read Yosys JSON netlist: %s" % e)


def _bit_names(mod):
    """Map each net bit id to its (preferred) net name.

    Yosys emits auto-generated names beginning with '$' for internal nets. A
    public name is always preferred, because a finding reported against
    `$auto$proc_dff.cc:123` is not actionable by the engineer reading it.
    """
    out = {}
    for name, info in (mod.get("netnames") or {}).items():
        for idx, bit in enumerate(info.get("bits") or []):
            if not isinstance(bit, int):
                continue
            prev = out.get(bit)
            if prev is None or (prev.startswith("$") and not name.startswith("$")):
                out[bit] = name
    return out


def _port_bits(mod):
    bits = set()
    for info in (mod.get("ports") or {}).values():
        for b in info.get("bits") or []:
            if isinstance(b, int):
                bits.add(b)
    return bits


def _first_bit(conn):
    for b in conn or []:
        if isinstance(b, int):
            return b
    return None


def _is_boundary_cell(ctype, mods):
    """True if `ctype` is an unflattened blackbox/boundary primitive.

    DX-150: `flatten` cannot inline a submodule that carries an `inout` port
    (e.g. a sky130_ef_io pad with a bidirectional PAD pin), so those instances
    survive as separate modules with zero internal cells -- an empty shell
    whose pins are the entire "implementation". Yosys native cell types
    ($adff, $and, ...) start with '$' and are never module names, so they
    never match here; only a genuine unflattened submodule instance can.

    A module with ZERO cells (or an explicit `blackbox`/`whitebox` attribute)
    has no sequential logic of its own to sample a reset AS DATA -- it is a
    boundary primitive, and pins that connect to it are pass-through wiring,
    not a data consumer. A module that still has real cells inside it (i.e.
    flatten simply wasn't run, or genuinely couldn't get to it for some other
    reason) is NOT treated as a boundary -- its internal logic is still real
    and any reset-as-data inside it must still be caught.
    """
    m = mods.get(ctype)
    if m is None:
        return False
    attrs = m.get("attributes") or {}
    if attrs.get("blackbox") or attrs.get("whitebox"):
        return True
    return not (m.get("cells") or {})


def analyze(netlist, top=None):
    """Classify every reset in the design and report hygiene findings.

    Returns a dict whose `assessable` field is False when nothing could be
    examined -- an empty finding list from an unexamined design must never be
    presented as a clean one.
    """
    mods = netlist.get("modules") or {}
    if not mods:
        return {"assessable": False, "findings": None,
                "note": ("netlist contains no modules; nothing was examined, "
                         "which is NOT the same as nothing being wrong")}

    if top and top in mods:
        targets = {top: mods[top]}
    else:
        targets = {k: v for k, v in mods.items()
                   if not (v.get("attributes") or {}).get("blackbox")}
    if not targets:
        return {"assessable": False, "findings": None,
                "note": "no non-blackbox module to analyze"}

    resets = {}       # (module, net name) -> observations
    tied = []         # reset pins wired to a constant, not to a net
    flop_total = 0
    async_ff = sync_ff = no_reset_ff = 0

    for mname, mod in targets.items():
        names = _bit_names(mod)
        ports = _port_bits(mod)
        data_bits = set()
        reset_bits = set()
        cells = mod.get("cells") or {}

        for cname, cell in cells.items():
            ctype = cell.get("type")
            conns = cell.get("connections") or {}
            params = cell.get("parameters") or {}

            if ctype in _NO_RESET_FF:
                flop_total += 1
                no_reset_ff += 1
            elif ctype in _ASYNC_FF or ctype in _SYNC_FF or ctype in _SR_FF:
                flop_total += 1
                if ctype in _ASYNC_FF:
                    pin, kind, polkey = _ASYNC_FF[ctype], "async", "ARST_POLARITY"
                    async_ff += 1
                elif ctype in _SYNC_FF:
                    pin, kind, polkey = _SYNC_FF[ctype], "sync", "SRST_POLARITY"
                    sync_ff += 1
                else:
                    pin, kind, polkey = _SR_FF[ctype], "set_reset", "CLR_POLARITY"
                    async_ff += 1

                bit = _first_bit(conns.get(pin))
                if bit is None:
                    # A reset pin tied to a CONSTANT rather than driven by a
                    # net. Recorded, never skipped: a reset held permanently
                    # inactive means those flops never reset at all, and
                    # dropping it here would be the same "absence reads as
                    # clean" failure this module exists to prevent.
                    tied.append({"module": mname, "cell": cname, "pin": pin,
                                 "value": conns.get(pin)})
                    continue
                reset_bits.add(bit)
                net = names.get(bit, "%s.%s" % (mname, pin))
                pol = params.get(polkey)
                try:
                    pol = int(str(pol), 0) if pol is not None else None
                except (TypeError, ValueError):
                    pol = None

                # KEYED BY (MODULE, NET), NOT BY NET NAME ALONE.
                # `rst_n` is one of the most reused identifiers in any design,
                # so keying on the bare name merged unrelated nets from
                # different modules into a single reset. Two modules that were
                # each internally consistent -- one active-low, one active-high
                # -- then reported a GATING `mixed_reset_polarity` that did not
                # exist. A false positive on a gating metric is not a cosmetic
                # problem: it makes a correct design unclosable, which teaches
                # everyone to waive the check.
                key = (mname, net)
                r = resets.setdefault(key, {
                    "net": net, "module": mname, "kinds": set(),
                    "polarities": set(), "flop_count": 0,
                    "driven_by_port": bit in ports, "cells": []})
                r["kinds"].add(kind)
                if pol is not None:
                    r["polarities"].add(pol)
                r["flop_count"] += 1
                if len(r["cells"]) < 5:
                    r["cells"].append(cname)

        # Yosys can merge equivalent synchronous clears into an ordinary
        # combinational cone whose output drives SRST. Walk that cone backward
        # from actual reset pins so its input uses remain reset control rather
        # than being mislabeled as sampled data.
        reset_control_bits = set(reset_bits)
        reset_control_uses = set()
        changed = True
        while changed:
            changed = False
            for cname, cell in cells.items():
                ctype = cell.get("type")
                if _is_boundary_cell(ctype, mods):
                    continue
                conns = cell.get("connections") or {}
                directions = cell.get("port_directions") or {}
                if not directions:
                    continue
                output_bits = {
                    bit for pinname, conn in conns.items()
                    if directions.get(pinname) in ("output", "inout")
                    for bit in (conn or []) if isinstance(bit, int)
                }
                if not (output_bits & reset_control_bits):
                    continue
                for pinname, conn in conns.items():
                    if directions.get(pinname) not in ("input", "inout"):
                        continue
                    reset_control_uses.add((cname, pinname))
                    for bit in conn or []:
                        if isinstance(bit, int) and bit not in reset_control_bits:
                            reset_control_bits.add(bit)
                            changed = True

        # Collect data-side bits so reset-as-data can be detected. Only input
        # pins count; outputs merely name the result of logic and are not a use.
        # Inputs on the generated reset-control cone above are control uses.
        for cname, cell in cells.items():
            ctype = cell.get("type")
            conns = cell.get("connections") or {}
            if _is_boundary_cell(ctype, mods):
                continue
            directions = cell.get("port_directions") or {}
            for pinname, conn in conns.items():
                if pinname in ("ARST", "SRST", "CLR", "SET", "CLK", "Q", "ALOAD"):
                    continue
                if directions and directions.get(pinname) not in ("input", "inout"):
                    continue
                if (cname, pinname) in reset_control_uses:
                    continue
                for b in conn or []:
                    if isinstance(b, int):
                        data_bits.add(b)

        for (rmod, rnet), r in resets.items():
            if rmod != mname:
                continue
            r["also_used_as_data"] = bool(
                {b for b, n in names.items() if n == rnet} & data_bits)

    if not resets and not tied:
        return {"assessable": True, "findings": [], "resets": [],
                "gating_findings": 0, "advisory_findings": 0,
                "reset_net_count": 0, "constant_tied_resets": 0,
                "flop_total": flop_total, "async_ff": async_ff,
                "sync_ff": sync_ff, "no_reset_ff": no_reset_ff,
                "basis": "elaborated_yosys_netlist",
                "note": ("no reset-bearing flops found. If the design is "
                         "expected to have a reset, THAT is the finding: "
                         "%d flop(s) carry no reset at all." % no_reset_ff)}

    findings = []
    for t in tied:
        findings.append({
            "kind": "reset_tied_to_constant", "net": None,
            "module": t["module"], "severity": "advisory",
            "basis": "yosys_connectivity",
            "detail": ("the %s pin of '%s' is tied to a constant rather than "
                       "driven by a reset net, so that flop never resets. "
                       "Sometimes deliberate after optimisation; confirm it is."
                       % (t["pin"], t["cell"]))})

    for (mname_k, net), r in sorted(resets.items()):
        low_name = bool(_ACTIVE_LOW_NAME.search(net))
        pols = r["polarities"]
        kinds = r["kinds"]

        # (1) STRUCTURAL, GATING. The same reset net used both async and sync.
        # One of the two is almost certainly not what the designer intended, and
        # the flops will leave reset on different cycles.
        if len({k for k in kinds if k in ("async", "sync")}) > 1:
            findings.append({
                "kind": "mixed_reset_style", "net": net, "module": r["module"],
                "severity": "gating", "basis": "yosys_cell_type",
                "detail": ("'%s' drives BOTH asynchronous and synchronous reset "
                           "pins (%d flops). The two groups leave reset on "
                           "different cycles, so the design has no single "
                           "well-defined reset boundary."
                           % (net, r["flop_count"])),
                "evidence_cells": r["cells"]})

        # (2) STRUCTURAL, GATING. One net, two polarities: half the design
        # resets while the other half runs.
        if len(pols) > 1:
            findings.append({
                "kind": "mixed_reset_polarity", "net": net, "module": r["module"],
                "severity": "gating", "basis": "yosys_cell_parameter",
                "detail": ("'%s' is used with BOTH active-high and active-low "
                           "polarity across %d flops. On assertion, one group "
                           "resets and the other keeps running."
                           % (net, r["flop_count"])),
                "evidence_cells": r["cells"]})

        # (3) STRUCTURAL, GATING. A reset that is also a data input. Sometimes
        # deliberate, but it defeats reset-tree treatment and is a classic
        # source of reset-domain-crossing bugs, so it is surfaced loudly.
        if r.get("also_used_as_data"):
            findings.append({
                "kind": "reset_used_as_data", "net": net, "module": r["module"],
                "severity": "gating", "basis": "yosys_connectivity",
                "detail": ("'%s' drives reset pins AND ordinary data/logic "
                           "inputs. If intentional, waive it explicitly; "
                           "otherwise the reset is being sampled as data."
                           % net)})

        # (4) NAMING CONVENTION, ADVISORY. Cannot be proven from structure --
        # a net named `rst_n` that is active-high is legal silicon and illegal
        # communication. Reported, never gated.
        if pols and low_name and 1 in pols:
            findings.append({
                "kind": "polarity_contradicts_name", "net": net,
                "module": r["module"], "severity": "advisory",
                "basis": "naming_convention_heuristic",
                "detail": ("'%s' is named active-low but is used ACTIVE-HIGH. "
                           "Legal, but every future reader will assume the "
                           "opposite." % net)})
        elif pols and not low_name and _RESETish.search(net) and 0 in pols:
            findings.append({
                "kind": "polarity_contradicts_name", "net": net,
                "module": r["module"], "severity": "advisory",
                "basis": "naming_convention_heuristic",
                "detail": ("'%s' is named active-high but is used ACTIVE-LOW; "
                           "consider '%s_n'." % (net, net))})

        # (5) TOPOLOGY HEURISTIC, ADVISORY. The canonical async-reset bug is
        # not assertion but DE-ASSERTION: releasing an async reset
        # asynchronously violates recovery/removal and can drive flops
        # metastable. A reset arriving directly from a port with nothing
        # between it and the flops has no de-assertion synchronizer.
        if "async" in kinds and r["driven_by_port"]:
            findings.append({
                "kind": "async_reset_not_synchronized", "net": net,
                "module": r["module"], "severity": "advisory",
                "basis": "port_drives_arst_directly",
                "detail": ("async reset '%s' reaches %d flop(s) directly from a "
                           "top-level port with no intervening logic, so its "
                           "DE-assertion is unsynchronized. Asserting "
                           "asynchronously is fine; RELEASING asynchronously "
                           "violates recovery/removal timing. If the "
                           "synchronizer lives outside this module, this is "
                           "expected -- which is why it does not gate."
                           % (net, r["flop_count"]))})

    gating = [f for f in findings if f["severity"] == "gating"]
    return {
        "assessable": True,
        "findings": findings,
        "gating_findings": len(gating),
        "advisory_findings": len(findings) - len(gating),
        "resets": [{"net": r["net"], "module": r["module"],
                    "kinds": sorted(r["kinds"]),
                    "polarities": sorted(r["polarities"]),
                    "flop_count": r["flop_count"],
                    "driven_by_port": r["driven_by_port"],
                    "also_used_as_data": r.get("also_used_as_data", False)}
                   for r in sorted(resets.values(), key=lambda x: x["net"])],
        "reset_net_count": len(resets),
        "constant_tied_resets": len(tied),
        "flop_total": flop_total, "async_ff": async_ff, "sync_ff": sync_ff,
        "no_reset_ff": no_reset_ff,
        "basis": "elaborated_yosys_netlist",
    }
