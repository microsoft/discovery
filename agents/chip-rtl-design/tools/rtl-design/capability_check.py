"""Build-time capability gate for chip-rtl-design. NON-VACUOUS BY DESIGN.

Run during `podman build`; a non-zero exit fails the build.

Two halves:

1. RESET HYGIENE is exercised against synthetic Yosys netlists whose defects are
   known in advance -- a net used at two polarities, a net used both async and
   sync, a reset also sampled as data. Crucially it also asserts the NEGATIVE
   case: a clean design must produce zero gating findings. A checker that fires
   on everything is as useless as one that fires on nothing.

2. The real Yosys toolchain is exercised end to end on a tiny design with a
   DELIBERATE inferred latch, so the image cannot ship with a broken frontend.
"""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, "/app")

import reset_hygiene  # noqa: E402
import synchronizer_hygiene  # noqa: E402


def _mod(cells, netnames, ports=None):
    return {"modules": {"top": {"ports": ports or {},
                                "cells": cells, "netnames": netnames}}}


def _ff(ctype, rstpin, rstbit, pol, d=10, q=11):
    polkey = {"ARST": "ARST_POLARITY", "SRST": "SRST_POLARITY"}[rstpin]
    return {"type": ctype, "parameters": {polkey: str(pol)},
            "connections": {"CLK": [2], rstpin: [rstbit], "D": [d], "Q": [q]}}


def check_reset_hygiene():
    NN = {"clk": {"bits": [2]}, "rst_n": {"bits": [3]}, "d": {"bits": [10]},
          "q": {"bits": [11]}}

    # (a) CLEAN: one async reset, one polarity, not used as data, and driven
    #     through logic rather than straight from a port.
    clean = _mod({"f1": _ff("$adff", "ARST", 3, 0),
                  "f2": _ff("$adff", "ARST", 3, 0)}, NN)
    r = reset_hygiene.analyze(clean, "top")
    assert r["assessable"] and r["gating_findings"] == 0, r
    assert r["async_ff"] == 2 and r["reset_net_count"] == 1, r

    # (b) MIXED POLARITY on one net -- half the design resets, half runs on.
    mixed_pol = _mod({"f1": _ff("$adff", "ARST", 3, 0),
                      "f2": _ff("$adff", "ARST", 3, 1)}, NN)
    r = reset_hygiene.analyze(mixed_pol, "top")
    kinds = {f["kind"] for f in r["findings"]}
    assert "mixed_reset_polarity" in kinds, r
    assert r["gating_findings"] >= 1, r

    # (c) MIXED STYLE -- same net async on one flop, sync on another.
    mixed_style = _mod({"f1": _ff("$adff", "ARST", 3, 0),
                        "f2": _ff("$sdff", "SRST", 3, 0)}, NN)
    r = reset_hygiene.analyze(mixed_style, "top")
    assert "mixed_reset_style" in {f["kind"] for f in r["findings"]}, r

    # (d) RESET AS DATA -- the reset net also feeds a data pin.
    as_data = _mod({"f1": _ff("$adff", "ARST", 3, 0),
                    "u1": {"type": "$and", "parameters": {},
                           "connections": {"A": [3], "B": [10], "Y": [12]}}},
                   NN)
    r = reset_hygiene.analyze(as_data, "top")
    assert "reset_used_as_data" in {f["kind"] for f in r["findings"]}, r

    # (e) NAMING CONTRADICTION is ADVISORY, never gating: `rst_n` used
    #     active-high is legal silicon and illegal communication.
    named = _mod({"f1": _ff("$adff", "ARST", 3, 1)}, NN)
    r = reset_hygiene.analyze(named, "top")
    pol = [f for f in r["findings"] if f["kind"] == "polarity_contradicts_name"]
    assert pol and pol[0]["severity"] == "advisory", r
    assert r["gating_findings"] == 0, (
        "a naming-convention finding must NOT gate: %r" % r)

    # (f) UNSYNCHRONIZED async reset straight from a port -- advisory.
    ported = _mod({"f1": _ff("$adff", "ARST", 3, 0)}, NN,
                  ports={"rst_n": {"direction": "input", "bits": [3]}})
    r = reset_hygiene.analyze(ported, "top")
    unsync = [f for f in r["findings"]
              if f["kind"] == "async_reset_not_synchronized"]
    assert unsync and unsync[0]["severity"] == "advisory", r

    # (g) FAIL CLOSED: an empty or unreadable netlist is NOT a clean one.
    r = reset_hygiene.analyze({"modules": {}}, "top")
    assert r["assessable"] is False and r["findings"] is None, r
    try:
        reset_hygiene.load("/definitely/not/a/netlist.json")
        raise AssertionError("unreadable netlist did not raise")
    except reset_hygiene.NetlistUnavailable:
        pass

    # (h) A design with flops but NO reset at all must be reported, not silent.
    noreset = _mod({"f1": {"type": "$dff", "parameters": {},
                           "connections": {"CLK": [2], "D": [10], "Q": [11]}}},
                   NN)
    r = reset_hygiene.analyze(noreset, "top")
    assert r["assessable"] and r["no_reset_ff"] == 1 and "no reset" in r["note"], r


def _sync_mod(cells, netnames, ports):
    return {"modules": {"top": {"ports": ports, "cells": cells,
                                "netnames": netnames}}}


def _bus_ff(ctype, d, q, en=None):
    conn = {"CLK": [2], "D": list(d), "Q": list(q)}
    if en is not None:
        conn["EN"] = [en]
    return {"type": ctype, "parameters": {}, "connections": conn}


def check_synchronizer_hygiene():
    """Per-bit synchronization of a bus must fire; a qualified capture must not."""
    PORTS = {"clk": {"direction": "input", "bits": [2]},
             "data_in": {"direction": "input", "bits": [10, 11, 12, 13]}}
    NN = {"clk": {"bits": [2]}, "data_in": {"bits": [10, 11, 12, 13]},
          "data_in_ff1": {"bits": [20, 21, 22, 23]},
          "data_in_ff2": {"bits": [30, 31, 32, 33]},
          "data_in_cap": {"bits": [20, 21, 22, 23]},
          "in_valid_ff1": {"bits": [7]}}

    # (a) DEFECT: 4-bit port -> unenabled reg -> second unenabled reg.
    bad = _sync_mod({"s1": _bus_ff("$sdff", [10, 11, 12, 13], [20, 21, 22, 23]),
                     "s2": _bus_ff("$sdff", [20, 21, 22, 23], [30, 31, 32, 33])},
                    NN, PORTS)
    r = synchronizer_hygiene.analyze(bad, "top")
    kinds = {f["kind"] for f in r["findings"]}
    assert "multi_bit_port_synchronized_per_bit" in kinds, r
    assert r["gating_findings"] == 1, r

    # (b) CLEAN: one capture register under a real shared enable.
    good = _sync_mod(
        {"cap": _bus_ff("$sdffe", [10, 11, 12, 13], [20, 21, 22, 23], en=7)},
        NN, PORTS)
    r = synchronizer_hygiene.analyze(good, "top")
    assert r["gating_findings"] == 0, r
    assert r["qualified_capture_buses"] == 1, r

    # (c) A 1-BIT control may legitimately use a 2-flop chain -- it must NOT gate.
    ONE = {"clk": {"direction": "input", "bits": [2]},
           "in_valid": {"direction": "input", "bits": [10]}}
    one = _sync_mod({"s1": _bus_ff("$sdff", [10], [20]),
                     "s2": _bus_ff("$sdff", [20], [30])},
                    {"clk": {"bits": [2]}, "in_valid": {"bits": [10]}}, ONE)
    r = synchronizer_hygiene.analyze(one, "top")
    assert r["gating_findings"] == 0, (
        "a single-bit 2-flop synchronizer is CORRECT and must never gate: %r" % r)

    # (d) A CONSTANT enable is not a qualifier -- it must not launder the defect.
    const_en = _sync_mod(
        {"s1": {"type": "$sdffe", "parameters": {},
                "connections": {"CLK": [2], "D": [10, 11, 12, 13],
                                "Q": [20, 21, 22, 23], "EN": ["1"]}},
         "s2": _bus_ff("$sdff", [20, 21, 22, 23], [30, 31, 32, 33])},
        NN, PORTS)
    r = synchronizer_hygiene.analyze(const_en, "top")
    assert r["gating_findings"] == 1, (
        "EN tied to a constant is an unconditional register wearing an enable "
        "pin; treating it as a qualified capture would pass the defect: %r" % r)

    # (e) A single unenabled register is a PIPELINE stage, not a synchronizer.
    pipe = _sync_mod(
        {"s1": _bus_ff("$sdff", [10, 11, 12, 13], [20, 21, 22, 23])}, NN, PORTS)
    r = synchronizer_hygiene.analyze(pipe, "top")
    assert r["gating_findings"] == 0, (
        "one register stage is not a synchronizer chain: %r" % r)

    # (f) FAIL CLOSED: an empty netlist is NOT a clean one.
    r = synchronizer_hygiene.analyze({"modules": {}}, "top")
    assert r["assessable"] is False and r["findings"] is None, r


def check_yosys_end_to_end():
    """Prove the real frontend works AND that a real defect is detected."""
    d = tempfile.mkdtemp()
    v = os.path.join(d, "lat.v")
    with open(v, "w") as fh:
        # `en` low leaves `q` unassigned -> Yosys infers a $dlatch. If this
        # stops being detected, the tool's primary gate has silently died.
        fh.write("module lat(input en, input d, output reg q);\n"
                 "  always @* if (en) q = d;\n"
                 "endmodule\n")
    ys = os.path.join(d, "s.ys")
    with open(ys, "w") as fh:
        fh.write("read_verilog %s\nhierarchy -check -top lat\nproc\nopt -purge\n"
                 "stat\n" % v)
    p = subprocess.run(["yosys", "-s", ys], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-800:]
    assert "dlatch" in p.stdout, (
        "Yosys did not report the deliberate inferred latch; the latch gate is "
        "not actually working:\n" + p.stdout[-800:])


def main():
    check_reset_hygiene()
    check_synchronizer_hygiene()
    check_yosys_end_to_end()
    print("RTL_DESIGN_CAPABILITY_OK")


if __name__ == "__main__":
    main()
