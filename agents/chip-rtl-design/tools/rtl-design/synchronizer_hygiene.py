"""Structural synchronizer hygiene: catch a multi-bit payload synchronized BIT-BY-BIT.

WHY THIS EXISTS
---------------
A 2-flop synchronizer resolves metastability for ONE bit. Applied independently to
every bit of a bus it resolves each bit on a possibly different edge, so the
"synchronized" value can be a combination that never existed on the source side.
More flop stages do not fix it -- coherency is not a settling-time problem.

Measured on `mytop4-hiersoc` / `myTop4_soc`: the blessed `rtl.2` gave `data_in[7:0]`
its own `data_in_ff1/ff2` chain, and the defect reached a blessed RTL attempt and was
only caught by the downstream CDC gate, because RTL hygiene checked latches, undriven
nets and reset style -- and nothing about synchronizer shape.

THE DISCRIMINATOR IS MEASURED, NOT ASSUMED
------------------------------------------
Elaborated with Yosys (`proc; flatten; opt -purge`), the two shapes are unambiguous:

    rtl.2 (defect) data_in[7:0] -> $sdff  EN=None  -> Q feeds D of another $sdff
    rtl.4 (fixed)  data_in[7:0] -> $sdffe EN=<net> -> Q feeds the consumers directly

So the defect signature is: an input port of width >= 2 captured by an UNENABLED
flop whose Q drives another flop's D directly. The clean signature is a capture
register with a real shared enable -- the synchronized qualifier.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not decide which inputs are asynchronous; that needs a domain map and belongs
to the CDC/RDC gate. It reports a SHAPE that is wrong regardless of domain: if the bus
is asynchronous this is the coherency defect, and if it is synchronous the chain is a
pointless two-cycle delay. Grouping a separate 1-bit port into the same logical payload
(e.g. `in_last` alongside `data_in`) also needs a domain map, so sibling single-bit
chains are reported as ADVISORY context, never as gating.
"""

import re

#: Flop cell types that carry a clock enable, i.e. can be a QUALIFIED capture.
_ENABLED_FF = {"$dffe", "$adffe", "$sdffe", "$sdffce", "$dffsre", "$aldffe"}
#: Flop cell types with no enable pin -- a bare register stage.
_PLAIN_FF = {"$dff", "$ff", "$adff", "$sdff", "$dffsr", "$aldff"}
_ALL_FF = _ENABLED_FF | _PLAIN_FF

#: Pins that are control, not data. Everything else carrying a bit is a data use.
_CONTROL_PINS = {"CLK", "EN", "ARST", "SRST", "CLR", "SET", "ALOAD", "AD", "Q"}

_CLOCKish = re.compile(r"clk|clock", re.I)
_RESETish = re.compile(r"rst|reset|clr|clear", re.I)


class NetlistUnavailable(Exception):
    """Raised when the JSON netlist cannot be read. Never becomes 'clean'."""


def _ints(bits):
    return [b for b in (bits or []) if isinstance(b, int)]


def _real_enable(cell):
    """The EN net, or None when absent or tied to a constant.

    A constant enable is not a qualifier: `EN=1'b1` is an unconditional register
    wearing an enable pin, and treating it as a qualified capture would let the
    exact defect through under a different cell type.
    """
    if cell.get("type") not in _ENABLED_FF:
        return None
    en = _ints(cell.get("connections", {}).get("EN"))
    return en or None


def _bit_names(mod):
    out = {}
    for name, info in (mod.get("netnames") or {}).items():
        for bit in _ints(info.get("bits")):
            prev = out.get(bit)
            if prev is None or (prev.startswith("$") and not name.startswith("$")):
                out[bit] = name
    return out


def _input_ports(mod):
    """Input ports, excluding clocks and resets, as {name: [bits]}."""
    out = {}
    for name, info in (mod.get("ports") or {}).items():
        if info.get("direction") != "input":
            continue
        if _CLOCKish.search(name) or _RESETish.search(name):
            continue
        bits = _ints(info.get("bits"))
        if bits:
            out[name] = bits
    return out


def _flops(mod):
    return {n: c for n, c in (mod.get("cells") or {}).items()
            if c.get("type") in _ALL_FF}


def analyze(netlist, top=None):
    """Report synchronizer-shape findings for the top module.

    `assessable` is False when nothing could be examined -- an empty finding list
    from an unexamined design must never be presented as a clean one.
    """
    mods = netlist.get("modules") or {}
    if not mods:
        return {"assessable": False, "findings": None,
                "note": "netlist contains no modules; synchronizer shape NOT assessed"}
    if top and top in mods:
        mod = mods[top]
    elif len(mods) == 1:
        mod = next(iter(mods.values()))
    else:
        return {"assessable": False, "findings": None,
                "note": "top module %r not present in netlist; NOT assessed" % top}

    flops = _flops(mod)
    if not flops:
        return {"assessable": True, "findings": [], "gating_findings": 0,
                "multi_bit_ports": 0, "qualified_capture_buses": 0,
                "basis": "elaborated_netlist_structure",
                "note": "no sequential cells; nothing to synchronize"}

    names = _bit_names(mod)
    ports = _input_ports(mod)

    # Bit -> the flops that SAMPLE it on D, and the flops that DRIVE it on Q.
    d_users, q_drivers = {}, {}
    for cn, c in flops.items():
        for b in _ints(c.get("connections", {}).get("D")):
            d_users.setdefault(b, []).append((cn, c))
        for b in _ints(c.get("connections", {}).get("Q")):
            q_drivers[b] = (cn, c)

    # Any non-flop, non-control use of a bit means the stage-1 output is consumed
    # as data, so a following flop is a pipeline, not a second synchronizer stage.
    combi_users = set()
    for cn, c in (mod.get("cells") or {}).items():
        if c.get("type") in _ALL_FF:
            continue
        for pin, conn in (c.get("connections") or {}).items():
            if pin in _CONTROL_PINS:
                continue
            combi_users.update(_ints(conn))

    findings = []
    qualified, singlebit_chains = [], []
    multi_bit_ports = 0

    for pname, pbits in sorted(ports.items()):
        stage1 = []
        seen = set()
        for b in pbits:
            for cn, c in d_users.get(b, []):
                if cn not in seen:
                    seen.add(cn)
                    stage1.append((cn, c))
        if not stage1:
            continue
        width = len(pbits)
        if width >= 2:
            multi_bit_ports += 1

        enables, chained = set(), []
        for cn, c in stage1:
            en = _real_enable(c)
            if en:
                enables.add(tuple(en))
                continue
            # Unenabled stage. Is its Q fed straight into another flop's D?
            qbits = _ints(c.get("connections", {}).get("Q"))
            for qb in qbits:
                if qb in combi_users:
                    continue
                for cn2, _c2 in d_users.get(qb, []):
                    if cn2 != cn:
                        chained.append((cn, cn2, qb))
                        break
                if chained and chained[-1][0] == cn:
                    break

        if enables and not chained:
            qualified.append({
                "port": pname, "width": width,
                "enable_nets": sorted({names.get(e[0], "bit%d" % e[0])
                                       for e in enables}),
                "coherent": len(enables) == 1})
            continue

        if not chained:
            continue

        if width >= 2:
            findings.append({
                "kind": "multi_bit_port_synchronized_per_bit",
                "severity": "gating",
                "net": pname,
                "width": width,
                "stages": sorted({c for pair in chained for c in pair[:2]}),
                "detail": (
                    "input port '%s' is %d bits wide and each bit is captured by an "
                    "UNENABLED register whose output feeds a second register stage -- "
                    "a per-bit 2-flop synchronizer. A 2-flop synchronizer is valid for "
                    "ONE bit; applied per-bit to a bus the resolved bits need never "
                    "have coexisted on the source side. Adding stages does not fix "
                    "this. Capture the payload ONCE under a synchronized qualifier."
                    % (pname, width))})
        else:
            singlebit_chains.append(pname)

    # A 1-bit 2-flop chain is CORRECT in isolation, so it is only worth raising
    # when a bus on the same boundary was already flagged -- it may belong to the
    # same logical payload, which structure alone cannot prove.
    if singlebit_chains and any(f["severity"] == "gating" for f in findings):
        findings.append({
            "kind": "single_bit_synchronizers_beside_flagged_bus",
            "severity": "advisory",
            "net": ", ".join(sorted(singlebit_chains)),
            "detail": (
                "these 1-bit ports also use a 2-flop synchronizer, which is valid "
                "for a standalone control bit. If any of them is a QUALIFIER or "
                "part of the same payload as a flagged bus, it must be captured "
                "with it rather than resolved independently. Structure cannot "
                "decide this; the domain map can.")})

    gating = sum(1 for f in findings if f["severity"] == "gating")
    return {
        "assessable": True,
        "findings": findings,
        "gating_findings": gating,
        "multi_bit_ports": multi_bit_ports,
        "qualified_capture_buses": len(qualified),
        "qualified_captures": qualified,
        "basis": "elaborated_netlist_structure",
        "note": ("multi-bit payloads must be captured once under a synchronized "
                 "qualifier; per-bit synchronization of a bus is the defect"),
    }
