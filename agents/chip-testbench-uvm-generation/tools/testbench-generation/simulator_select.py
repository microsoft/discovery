#!/usr/bin/env python3
"""simulator_select.py -- pick a simulator that can actually ELABORATE the DUT.

WHY THIS EXISTS (measured 2026-09-26, reproduced 2026-09-29)
------------------------------------------------------------
A container that ships two simulators can have a per-FILE syntax incompatibility
with the DEFAULT one. Blessed `bsum16.v` declares:

    localparam reg [15:0] SumInit = 16'h0000;

Icarus Verilog 11.0 rejects that line with a syntax error under EVERY generation
flag -- `-g2005`, `-g2005-sv`, `-g2009` and `-g2012` all exit 2 -- while Verilator
5.036 elaborates the identical file cleanly. Re-measured 2026-09-29 in
`chip-testbench-generation:latest`; the untyped form (`localparam [15:0]`) compiles
under Icarus, so the incompatibility is specifically the explicit `reg` type on a
localparam.

Both `chip-testbench-uvm-generation` (DX-60) and `chip-functional-verification`
(DX-61) hard-coded `SIM=icarus` and hit this independently, and each was repaired by
hand-editing the generated Makefile. That is the recurrence this module removes: the
simulator is now chosen by PROBING, not by assumption.

WHY PROBE RATHER THAN SPECIAL-CASE THE SYNTAX
---------------------------------------------
Defaulting to Verilator "when the RTL has a typed localparam" is a syntactic guess
that fixes one construct and silently mis-handles the next one. Asking each
simulator whether it can elaborate THIS DUT answers the real question, costs one
cheap compile, and generalises to incompatibilities nobody has hit yet.

A substitution is RECORDED, never silent: the caller receives the rejected
simulator's exit code and first error line so the CDE can disclose that the DUT is
not portable to it. Silently swapping would hide a real portability constraint on
blessed RTL -- and the blessed RTL must never be edited to suit a simulator.

FAIL-CLOSED
-----------
When NO candidate elaborates, the preferred simulator is returned unchanged with
`substituted: False` and every probe result attached. The run then fails on its own
merits with the evidence already collected, rather than this module inventing a
choice that cannot work.
"""

import os
import shutil
import subprocess
import tempfile

#: Ordered Verilog candidates. Icarus stays FIRST: it is the historical default, it
#: is faster to elaborate, and keeping it preferred means a DUT it accepts sees no
#: behaviour change at all -- only a DUT it rejects moves.
VERILOG_CANDIDATES = ("icarus", "verilator")
VHDL_CANDIDATES = ("ghdl",)

#: Executable that must exist for a candidate to be probeable.
_BINARY = {"icarus": "iverilog", "verilator": "verilator", "ghdl": "ghdl"}


def _argv(sim, sources, top, std, out_dir):
    if sim == "icarus":
        # -g2012 is the most permissive generation mode Icarus offers, so a
        # rejection here is a genuine parser limit rather than a flag choice.
        return ["iverilog", "-g2012", "-o", os.path.join(out_dir, "a.out")] + sources
    if sim == "verilator":
        # --lint-only answers "can you parse/elaborate this", which is the
        # question. -Wno-fatal keeps STYLE warnings from being read as an
        # inability to elaborate; an unparseable file still exits non-zero.
        argv = ["verilator", "--lint-only", "-Wno-fatal"]
        if top:
            argv += ["--top-module", str(top)]
        return argv + sources
    if sim == "ghdl":
        return ["ghdl", "-s", "--std=%s" % (std or "08")] + sources
    return None


def available(sim):
    return bool(shutil.which(_BINARY.get(sim, sim)))


def probe(sim, sources, top=None, std="08", timeout=180):
    """Try to elaborate `sources` with `sim`. Never raises."""
    record = {"simulator": sim, "available": available(sim),
              "elaborates": False, "returncode": None, "error": None}
    if not record["available"]:
        record["error"] = "%s not installed in this image" % _BINARY.get(sim, sim)
        return record
    out_dir = tempfile.mkdtemp(prefix="simprobe-")
    try:
        argv = _argv(sim, [str(s) for s in sources], top, std, out_dir)
        if not argv:
            record["error"] = "no probe command defined for %r" % sim
            return record
        try:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            record["error"] = "elaboration probe timed out after %ss" % timeout
            return record
        except OSError as exc:
            record["error"] = "elaboration probe could not run: %s" % exc
            return record
        record["returncode"] = proc.returncode
        record["elaborates"] = proc.returncode == 0
        if not record["elaborates"]:
            combined = ((proc.stderr or "") + (proc.stdout or "")).strip()
            first = next((line.strip() for line in combined.splitlines()
                          if line.strip()), "")
            record["error"] = first[:400] or "exit %s with no diagnostic" % proc.returncode
        return record
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def select(sources, top=None, preferred=None, is_vhdl=False, std="08",
           candidates=None, timeout=180):
    """Choose the first candidate simulator that elaborates `sources`.

    Returns a record the caller should publish into its CDE: the choice, whether it
    is a substitution for the preferred simulator, and every probe result including
    the rejected simulator's own diagnostic.
    """
    order = tuple(candidates or (VHDL_CANDIDATES if is_vhdl else VERILOG_CANDIDATES))
    default = preferred or (order[0] if order else None)
    # The caller's preference must be probed FIRST, otherwise a stated preference
    # is silently overridden by whichever candidate happens to lead the list and
    # the result is reported as a "substitution" away from a simulator never tried.
    if default and default in order:
        order = (default,) + tuple(s for s in order if s != default)
    elif default and default in _BINARY:
        order = (default,) + order
    result = {"preferred": default, "selected": default, "substituted": False,
              "probed": False, "reason": None, "candidates": []}

    sources = [str(s) for s in (sources or [])]
    if not sources or not order:
        result["reason"] = "no sources to probe; kept the preferred simulator"
        return result

    result["probed"] = True
    for sim in order:
        record = probe(sim, sources, top=top, std=std, timeout=timeout)
        result["candidates"].append(record)
        if record["elaborates"]:
            result["selected"] = sim
            result["substituted"] = sim != default
            if result["substituted"]:
                rejected = next(
                    (c for c in result["candidates"]
                     if c["simulator"] == default and not c["elaborates"]), None)
                result["reason"] = (
                    "%s could not elaborate the DUT (%s); %s did. The DUT is "
                    "unchanged -- this records a real portability limit, it does "
                    "not work around one."
                    % (default, (rejected or {}).get("error") or "see candidates",
                       sim))
            else:
                result["reason"] = "%s elaborated the DUT" % sim
            return result

    result["reason"] = (
        "no available simulator elaborated the DUT; kept %s so the run fails on "
        "its own diagnostics rather than on an invented choice" % default)
    return result
