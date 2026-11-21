#!/usr/bin/env python3
"""
sdc_author.py -- constraint-COVERAGE accounting and provenance-carrying SDC
authoring for the chip-constraints-sdc tool.

TWO PROBLEMS, ONE ROOT CAUSE
============================
The lint path answers "did OpenSTA print words that look like complaints?" by
keyword-counting its prose. That has two consequences, and both come from the
same root: nothing ever enumerates the design's timing endpoints.

  1. NO COVERAGE DENOMINATOR. A regex that matches nothing yields 0 and closes
     the gate. "Zero complaints" and "nothing was examined" are the same
     observation. Constraint COVERAGE -- how many endpoints are constrained out
     of how many exist -- is the measurement that distinguishes them, and it
     cannot be recovered from prose.

  2. NO AUTHORING. The agent is instructed to infer an `author` intent and
     carries the Constraint (SDC) Authoring Skill, but the tool only ever
     rejects that scenario. Authoring needs the same enumeration: you cannot
     write `create_clock` without knowing which ports actually drive clock pins.

STRUCTURE IS DERIVABLE; INTENT IS NOT
=====================================
The split below is what makes safe authoring possible, and it is a hard line:

  DERIVABLE FROM THE NETLIST      MUST BE SUPPLIED (never inferred)
  ------------------------------  ---------------------------------------
  which ports drive clock pins    the clock PERIOD
  the endpoint population         input/output delay BUDGET
  which endpoints are covered     which paths are genuinely FALSE
  clock fan-out cones             MULTICYCLE intent

The netlist can prove `clk` is a clock. It CANNOT tell you it is 10 ns -- that
number lives in the specification.

*** AN INVENTED CLOCK PERIOD IS THE MOST DANGEROUS ARTIFACT THIS FLOW CAN
    PRODUCE. *** Synthesis targets it, CTS balances to it, STA closes against
it, ECO repairs to it and signoff blesses it -- and every one of those stages
reports SUCCESS. The whole flow then reports "timing met" against a period
nobody chose. So this module NEVER defaults a period. A clock with no supplied
period is not emitted at all; it is reported as a named hole and the run is
not_assessable for that clock. An SDC with a guessed number is worse than no
SDC, because the guess is invisible downstream.

EVERY EMITTED LINE CARRIES PROVENANCE
=====================================
Each constraint is written with a comment recording where it came from:
netlist-derived, or caller-supplied and from which field. A reader must never
have to guess whether a number was measured or assumed.
"""

import json
import os
import re
import subprocess

# Tcl that enumerates the design's timing structure as JSON-ish lines. Kept to
# widely-available OpenSTA/Tcl commands; anything unavailable simply yields an
# empty list, which callers MUST treat as not-assessable rather than as zero.
#
# CLKPORTS IS TRACED, NOT PARSED. A clock pin like `u_ff/CLK` sits on an
# INSTANCE; the port that drives it is a different object entirely, reached
# through the net. Deriving the port by splitting the pin path yields the
# instance name (`u_ff`), which matches no port and silently produces zero clock
# candidates -- an authoring tool that quietly writes nothing. So the connection
# is resolved here, in the tool that actually knows the netlist, and each line is
# emitted as `<port> <clock_pin>` so the evidence for every candidate travels
# with it.
_ENUM_TCL = r"""
proc _emit {tag items} {
  puts "__${tag}__BEGIN__"
  foreach i $items { puts $i }
  puts "__${tag}__END__"
}
# Clock pins: register pins the timing graph treats as clocks.
set _clkpins {}
catch {
  foreach _p [all_registers -clock_pins] { lappend _clkpins [get_full_name $_p] }
}
_emit CLKPINS $_clkpins
# Clock PORTS: preserve direct connections and trace input fan-out through buffers.
# Emitted as "<port> <clock_pin>" so the evidence stays attached to the claim.
set _clkports {}
set _clk_trace_ok 1
if {[catch {
  set _clock_pin_names [dict create]
  foreach _pin [all_registers -clock_pins] {
    dict set _clock_pin_names [get_full_name $_pin] 1
  }
  foreach _pin [all_registers -clock_pins] {
    set _net [get_nets -quiet -of_objects $_pin]
    if {$_net eq ""} { continue }
    foreach _port [get_ports -quiet -of_objects $_net] {
      lappend _clkports "[get_full_name $_port] [get_full_name $_pin]"
    }
  }
  # Register clock pins terminate native fan-in searches. Forward reachability
  # avoids that stop condition and does not depend on clock constraints existing.
  foreach _port [all_inputs] {
    foreach _sink [get_fanout -from $_port -flat -trace_arcs all] {
      set _name [get_full_name $_sink]
      if {[dict exists $_clock_pin_names $_name]} {
        lappend _clkports "[get_full_name $_port] $_name"
      }
    }
  }
} _clk_trace_error]} {
  set _clk_trace_ok 0
  puts "__CLKTRACE_ERROR__ $_clk_trace_error"
}
if {$_clk_trace_ok} {
  _emit CLKPORTS [lsort -unique $_clkports]
}
set _in {}
catch { foreach _p [all_inputs] { lappend _in [get_full_name $_p] } }
_emit INPUTS $_in
set _out {}
catch { foreach _p [all_outputs] { lappend _out [get_full_name $_p] } }
_emit OUTPUTS $_out
set _regs {}
catch { foreach _p [all_registers -data_pins] { lappend _regs [get_full_name $_p] } }
_emit REGPINS $_regs
set _clocks {}
catch { foreach _c [all_clocks] { lappend _clocks [get_name $_c] } }
_emit CLOCKS $_clocks
"""


def _section(text, tag):
    """Pull one __TAG__BEGIN__ .. __TAG__END__ block out of tool output.

    Returns None when the block is ABSENT -- which is different from an empty
    block. Absent means the enumeration never ran (old tool build, command not
    available, crash); empty means it ran and found nothing. Collapsing those
    two is exactly how a check that examined nothing comes to report no
    findings, so the distinction is preserved all the way to the verdict.
    """
    m = re.search(r"__" + re.escape(tag) + r"__BEGIN__\n(.*?)__"
                  + re.escape(tag) + r"__END__", text, re.S)
    if not m:
        return None
    return [l.strip() for l in m.group(1).splitlines() if l.strip()]


def enumerate_design(binname, work_dir, out_dir, reads, reader, top,
                     sdc=None, runner=None):
    """Enumerate ports/registers/clocks by running Tcl introspection.

    `sdc` is optional: with it, `all_clocks` reflects the constraints actually
    read, which is what makes coverage measurable; without it the enumeration is
    the raw structural population, which is what authoring needs.

    Returns a dict whose list fields are None when the corresponding block was
    absent. FAIL CLOSED: callers must treat None as not-assessable and MUST NOT
    substitute zero.
    """
    script = "{reads}\n{reader}\nlink_design {top}\n".format(
        reads=reads, reader=reader, top=top)
    if sdc:
        script += "read_sdc {}\n".format(sdc)
    script += _ENUM_TCL + "\nexit\n"
    sp = os.path.join(out_dir, "enumerate.tcl")
    open(sp, "w").write(script)
    if runner is None:
        proc = subprocess.run([binname, "-exit", sp], capture_output=True,
                              text=True, cwd=work_dir)
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        rc = proc.returncode
    else:  # injected for testing without a solver present
        out, rc = runner(sp)
    open(os.path.join(out_dir, "enumerate.log"), "w").write(out)
    return {
        "clock_pins": _section(out, "CLKPINS"),
        "clock_ports": _section(out, "CLKPORTS"),
        "clock_trace_errors": [line for line in out.splitlines()
                               if line.startswith("__CLKTRACE_ERROR__")],
        "inputs": _section(out, "INPUTS"),
        "outputs": _section(out, "OUTPUTS"),
        "register_data_pins": _section(out, "REGPINS"),
        "clocks": _section(out, "CLOCKS"),
        "returncode": rc,
        "log": "enumerate.log",
    }


def coverage(enum):
    """Turn an enumeration into a constraint-coverage record.

    THE DENOMINATOR IS THE POINT. `unclocked_indicators` counts words in a
    report; this counts endpoints against the population that exists. When the
    population cannot be established the answer is NOT ASSESSABLE -- never zero,
    and never a percentage computed from a denominator nobody measured.
    """
    regs = enum.get("register_data_pins")
    ins = enum.get("inputs")
    outs = enum.get("outputs")
    clocks = enum.get("clocks")
    assessable = regs is not None and clocks is not None
    total = None
    if assessable:
        total = len(regs) + len(ins or []) + len(outs or [])
    return {
        "assessable": assessable,
        "endpoint_population": total,
        "register_data_pins": None if regs is None else len(regs),
        "input_ports": None if ins is None else len(ins),
        "output_ports": None if outs is None else len(outs),
        "clocks_defined": None if clocks is None else len(clocks),
        "clock_names": clocks or [],
        "basis": "opensta_tcl_design_enumeration",
        "note": ("Endpoint POPULATION measured by design introspection, not by "
                 "keyword-counting a report. When any field is null the "
                 "population could not be established and constraint coverage "
                 "is NOT ASSESSABLE -- null must never be read as zero."),
    }


# ---------------------------------------------------------------------------
# Authoring
# ---------------------------------------------------------------------------

def _port_of_pin(pin):
    """Best-effort port name for a pin path ('inst/CLK' -> 'inst').

    ONLY a fallback for flat designs where a clock pin path really is the port.
    The authoritative answer comes from CLKPORTS, which traces the net; string
    surgery on a pin path returns the INSTANCE, not the driver.
    """
    return pin.rsplit("/", 1)[0] if "/" in pin else pin


_INHERITED_SOURCE = (
    "{} [INHERITED: no dedicated source was supplied for this number, so the "
    "clock's own period/frequency citation is reused and does NOT attribute "
    "this value]")


def _cited(value_source, clock_source):
    """Citation for a number that carries its own source, or a LABELLED fallback.

    A tool that authors a correct NUMBER can still emit a wrong PROVENANCE
    STRING for it by reusing a nearby variable. `set_clock_transition` and
    `set_clock_latency` are not the period, so when no dedicated source is
    supplied the fallback is marked INHERITED rather than silently letting the
    clock's period/frequency citation read as if it attributed these numbers.
    """
    return value_source if value_source else _INHERITED_SOURCE.format(
        clock_source)


_EXCEPTION_ENDPOINT_KEYS = (("from", "from", "from_pins"),
                            ("to", "to", "to_pins"))


def _exception_endpoints(spec):
    """Resolve the `-from`/`-to` endpoints of a timing exception.

    PORTS AND PINS ARE DIFFERENT OBJECTS. `get_ports` only ever resolves a
    top-level boundary port, so an INTERNAL register-to-register path class --
    the scan-shift `flop.Q -> next-flop.SCD` class, for one -- cannot be
    excepted with ports at all: the collection comes back empty and the
    exception constrains nothing while still reading like it applied.

    Returns `(tcl_parts, record, conflicts)`. A `conflicts` entry means the
    caller supplied BOTH a port and a pin pattern for the same direction, which
    would emit `-from` twice; that is reported, never silently resolved.
    """
    parts, record, conflicts = [], {}, []
    for flag, port_key, pin_key in _EXCEPTION_ENDPOINT_KEYS:
        port_pattern, pin_pattern = spec.get(port_key), spec.get(pin_key)
        if port_pattern and pin_pattern:
            conflicts.append(flag)
            continue
        pattern = port_pattern or pin_pattern
        if not pattern:
            continue
        collection = "get_ports" if port_pattern else "get_pins"
        parts += ["-" + flag, "[%s {%s}]" % (collection, pattern)]
        record[flag] = {"pattern": pattern, "object": collection}
    return parts, record, conflicts


_SDC_COMMAND = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)")


def sdc_command_census(text):
    """command name -> occurrence count for an SDC, comments excluded."""
    census = {}
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _SDC_COMMAND.match(stripped)
        if not match:
            continue
        census[match.group(1)] = census.get(match.group(1), 0) + 1
    return census


def carry_forward_check(baseline_text, authored_text, justified=None):
    """Compare an authored SDC against the SDC it supersedes.

    WHY THIS IS A GATE AND NOT A NICETY. A refresh that silently loses a
    directive class its predecessor carried is invisible downstream: the file
    still looks like a complete SDC, every later stage reads it without
    complaint, and the lost constraint simply stops being checked. Measured on
    this flow, an entire `set_max_transition`/`set_max_capacitance`/
    `set_max_fanout` block vanished between two consecutive attempts of the same
    stage and was caught only much later, by a downstream gate that failed
    CLOSED on a now-unassessable check -- had that gate instead reported zero
    violations, the loss would have shipped as a clean result.

    A class the caller DELIBERATELY removed is declared in `justified` (command
    plus a reason and a source) and is recorded as a disclosed removal. Anything
    else that disappeared is a regression. A count that merely SHRANK inside a
    still-present class is an observation, not a regression -- the endpoint
    population legitimately moves between attempts.

    A missing baseline returns `assessable: False`. That is an honest unknown,
    never a pass: with nothing to compare against, a dropped directive is
    undetectable here.
    """
    if baseline_text is None:
        return {
            "assessable": False,
            "pass": False,
            "note": ("no baseline SDC was supplied, so this authored SDC was "
                     "NOT compared against the one it supersedes. A directive "
                     "class dropped since the previous attempt cannot be "
                     "detected here -- supply the prior blessed SDC to make "
                     "this check real. Absent is NOT clean."),
            "basis": "sdc_command_census_vs_superseded_sdc",
        }
    before = sdc_command_census(baseline_text)
    after = sdc_command_census(authored_text)
    declared = {}
    for item in (justified or []):
        command = (item or {}).get("command")
        if command:
            declared[command] = item
    regressions, disclosed, shrank = [], [], []
    for command, count in sorted(before.items()):
        now = after.get(command, 0)
        if now == 0:
            entry = {"command": command, "baseline_count": count,
                     "authored_count": 0}
            item = declared.get(command)
            if item and item.get("reason") and item.get("source"):
                entry.update({"reason": item["reason"],
                              "source": item["source"]})
                disclosed.append(entry)
            else:
                regressions.append(entry)
        elif now < count:
            shrank.append({"command": command, "baseline_count": count,
                           "authored_count": now})
    return {
        "assessable": True,
        "pass": not regressions,
        "baseline_commands": before,
        "authored_commands": after,
        "dropped_without_justification": regressions,
        "dropped_with_justification": disclosed,
        "count_decreased": shrank,
        "basis": "sdc_command_census_vs_superseded_sdc",
    }


def derive_clock_candidates(enum):
    """Ports that structurally drive register clock pins.

    Structural evidence only. Being a clock is derivable; the PERIOD is not,
    which is why this returns candidates rather than constraints.

    Prefers the TRACED port->pin pairs. Returns None only when the enumeration
    genuinely did not run -- an empty list from a real run means a design with no
    clocked registers, which is a different (and reportable) fact.
    """
    pairs = enum.get("clock_ports")
    pins = enum.get("clock_pins")
    if pairs is None and pins is None:
        return None
    cands, seen = [], set()
    for line in (pairs or []):
        bits = line.split()
        if len(bits) < 2:
            continue
        port, pin = bits[0], bits[1]
        if port in seen:
            continue
        seen.add(port)
        cands.append({"port": port, "evidence_pin": pin,
                      "basis": "net_traced_from_register_clock_pin"})
    if cands:
        return cands
    # Fallback for flat netlists where the clock pin IS a port name. Labelled
    # distinctly so a reader can tell a traced candidate from an inferred one.
    ports = set(enum.get("inputs") or [])
    for p in (pins or []):
        if p in ports and p not in seen:
            seen.add(p)
            cands.append({"port": p, "evidence_pin": p,
                          "basis": "clock_pin_is_a_top_level_port"})
    return cands


def author_sdc(enum, intent, top="design"):
    """Author an SDC from DERIVED structure + SUPPLIED intent.

    Returns (lines, emitted, holes, port_classes). A HOLE is a constraint that could not be
    written because the intent behind it was not supplied. Holes are returned,
    never guessed, and never silently dropped: the caller reports them and marks
    the run not_assessable. `intent` shape:

        {"clocks": {"clk": {"period_ns": 10.0, "source": "spec DR-7"}},
         "clock_transition_ns": 0.1,
         "clock_transition_source": "spec SS6 clock_transition_ns",
         "clock_latency_ns": {"network_pre_cts": 0.3},
         "clock_latency_source": "spec SS6 clock_latency_ns.network_pre_cts",
         "input_delay_ns": {"value": 2.0, "source": "budget"},
         "output_delay_ns": {"value": 2.0, "source": "budget"},
         "macro_input_transition_ns": 0.1,
         "macro_output_load_pf": 0.05,
         "false_paths": [{"from": "...", "to": "...", "reason": "...",
                          "source": "cdc-signoff crossing id"}],
         "multicycle_paths": [{"from_pins": "*/Q", "to_pins": "*/SCD",
                               "multiplier": 2, "reason": "scan shift",
                               "source": "DFT-ATE shift spec"}],
         "case_analysis": [{"port": "scan_en", "value": 0, "reason": "...",
                            "source": "DFT-ATE mode table"}]}

    `clock_transition_source`/`clock_latency_source` exist because those two
    numbers are NOT the period: without them the citation falls back to the
    clock's own period/frequency source, and the fallback is labelled INHERITED
    so a reader never reads it as attribution.

    Timing exceptions take PORT patterns (`from`/`to`) or PIN patterns
    (`from_pins`/`to_pins`). Pins are required for any internal
    register-to-register path class -- `get_ports` resolves only boundary ports,
    so a port-only exception on an internal path matches nothing and constrains
    nothing while still reading as if it applied.
    """
    intent = intent or {}
    cands = derive_clock_candidates(enum)
    if cands is None:
        return None, [], [{"kind": "enumeration_unavailable",
                           "detail": ("design enumeration did not run, so no "
                                      "constraint can be derived; NOT a clean "
                                      "result")}], {}

    lines = ["# SDC authored by chip-constraints-sdc",
             "# Top: {}".format(top),
             "# EVERY line below records its provenance. Structure is derived",
             "# from the netlist; every NUMBER is caller-supplied. Nothing is",
             "# defaulted -- a constraint whose intent was not supplied is",
             "# reported as a hole instead of being invented.",
             ""]
    emitted, holes = [], []

    declared = intent.get("clocks") or {}
    for c in cands:
        port = c["port"]
        spec = declared.get(port) or declared.get(_port_of_pin(port)) or {}
        period = spec.get("period_ns")
        if period is None:
            holes.append({
                "kind": "clock_period_not_supplied", "port": port,
                "evidence_pin": c["evidence_pin"],
                "detail": ("'{}' structurally drives a register clock pin, but no "
                           "period was supplied. NOT EMITTED: an invented period "
                           "would be targeted by synthesis, balanced by CTS and "
                           "closed by STA, and every stage would report success "
                           "against a number nobody chose.".format(port))})
            continue
        src = spec.get("source") or "caller-supplied (no source recorded)"
        waveform = spec.get("waveform_ns")
        lines.append("# clock '{}': port drives {} [derived: netlist]".format(
            port, c["evidence_pin"]))
        lines.append("# period {} ns [supplied: {}]".format(period, src))
        clock_line = "create_clock -name {n} -period {p:.3f}".format(
            n=port, p=float(period))
        if isinstance(waveform, (list, tuple)) and len(waveform) == 2:
            clock_line += " -waveform {{{:.3f} {:.3f}}}".format(
                float(waveform[0]), float(waveform[1]))
        clock_line += " [get_ports {n}]".format(n=port)
        lines.append(clock_line)
        uncertainty = spec.get("uncertainty_ns")
        if uncertainty is not None:
            if isinstance(uncertainty, dict):
                setup = uncertainty.get("setup")
                hold = uncertainty.get("hold")
            else:
                setup = hold = uncertainty
            uncertainty_src = spec.get("uncertainty_source") or src
            lines.append("# clock uncertainty [supplied: {}]".format(
                uncertainty_src))
            if setup is not None:
                lines.append(
                    "set_clock_uncertainty -setup {:.3f} [get_clocks {}]".format(
                        float(setup), port))
            if hold is not None:
                lines.append(
                    "set_clock_uncertainty -hold {:.3f} [get_clocks {}]".format(
                        float(hold), port))
        transition = spec.get("transition_ns")
        transition_source = spec.get("transition_source")
        if transition is None:
            transition = intent.get("clock_transition_ns")
            transition_source = intent.get("clock_transition_source")
        if isinstance(transition, dict):
            transition_source = transition.get("source") or transition_source
            transition = transition.get("value")
        if transition is None:
            holes.append({
                "kind": "clock_transition_not_supplied", "port": port,
                "detail": ("'{}' has a supplied period but no clock transition. "
                           "NOT EMITTED: input slew is electrical timing intent "
                           "and must not be defaulted.".format(port))})
        else:
            transition_citation = _cited(transition_source, src)
            lines.append("# clock transition [supplied: {}]".format(
                transition_citation))
            lines.append(
                "set_clock_transition {:.3f} [get_clocks {}]".format(
                    float(transition), port))
            emitted.append({
                "constraint": "set_clock_transition", "clock": port,
                "value_ns": transition, "value_source": transition_citation,
                "value_source_is_dedicated": bool(transition_source)})

        latency = spec.get("network_latency_pre_cts_ns")
        latency_source = spec.get("network_latency_pre_cts_source")
        if latency is None:
            latency = intent.get("clock_latency_ns")
            latency_source = intent.get("clock_latency_source")
        if isinstance(latency, dict):
            latency_source = latency.get("source") or latency_source
            network = latency.get("network_pre_cts")
            latency = network if network is not None else latency.get("value")
        if latency is None:
            holes.append({
                "kind": "pre_cts_clock_latency_not_supplied", "port": port,
                "detail": ("'{}' has no pre-CTS network clock latency. NOT "
                           "EMITTED: latency is explicit clock-distribution "
                           "intent and must not be invented.".format(port))})
        else:
            latency_citation = _cited(latency_source, src)
            lines.append("# pre-CTS network clock latency [supplied: {}]".format(
                latency_citation))
            lines.append(
                "set_clock_latency {:.3f} [get_clocks {}]".format(
                    float(latency), port))
            emitted.append({
                "constraint": "set_clock_latency", "clock": port,
                "value_ns": latency, "phase": "pre_cts",
                "value_source": latency_citation,
                "value_source_is_dedicated": bool(latency_source)})
        lines.append("")
        emitted.append({"constraint": "create_clock", "port": port,
                        "period_ns": period, "period_source": src,
                        "uncertainty_ns": uncertainty,
                        "structure_basis": "netlist"})

    # SUPPLIED INTENT THAT MATCHED NOTHING IS A HOLE, NOT A NO-OP.
    # A caller who supplies a period for 'clk_i' when the port is 'clk' has done
    # the engineering work and reasonably believes the constraint landed. If the
    # mismatch is dropped quietly, the design ends up with an UNCONSTRAINED clock
    # while the request that would have constrained it is reported nowhere. That
    # is the same silent-underconstraint failure as an absent period, arrived at
    # from the opposite direction, so it is surfaced with the same severity.
    _cand_ports = {c["port"] for c in cands}
    for name in sorted(declared):
        if name in _cand_ports:
            continue
        holes.append({
            "kind": "supplied_clock_matched_no_port", "port": name,
            "detail": ("a period was supplied for '{}', but no such clock-driving "
                       "port exists in the netlist (candidates: {}). NOT EMITTED, "
                       "and NOT ignored: the caller believes this clock is "
                       "constrained and it is not.".format(
                           name, ", ".join(sorted(_cand_ports)) or "none"))})

    clk_names = [
        e["port"] for e in emitted if e["constraint"] == "create_clock"]
    # PORT CLASSIFICATION. Input ports are not interchangeable, and treating
    # them as one population produced two silent errors.
    #
    # (1) A CLOCK PORT that did not get a period -- because none was supplied --
    #     stayed in the I/O population and received `set_input_delay`. A clock
    #     port constrained as DATA is not merely useless: STA then times the
    #     clock port as a data path against some other clock, and the real clock
    #     remains undefined. The old filter excluded only ports whose clock was
    #     EMITTED, so the failure appeared exactly when the clock was least
    #     constrained.
    #
    # (2) An ASYNCHRONOUS RESET is not a timed input. Giving it an input delay
    #     invents a synchronous arrival for a signal that has none. Reset intent
    #     is a design decision (async? synchronized? which clock?), so it is
    #     NEVER guessed here -- the port is withheld from the I/O population and
    #     reported as a named hole for the caller to constrain deliberately.
    _all_clock_ports = {c["port"] for c in cands}
    declared_resets = set(intent.get("reset_ports") or [])
    unknown_resets = sorted(declared_resets
                            - set(enum.get("inputs") or [])
                            - set(enum.get("outputs") or []))
    for name in unknown_resets:
        holes.append({
            "kind": "declared_reset_matched_no_port", "port": name,
            "detail": ("'{}' was declared a reset port but no such port exists "
                       "in the netlist; it constrains nothing".format(name))})
    port_classes = {}
    for p in (enum.get("inputs") or []):
        if p in _all_clock_ports:
            port_classes[p] = "clock"
        elif p in declared_resets:
            port_classes[p] = "reset"
        else:
            port_classes[p] = "data"
    # A clock candidate that never received a period is an UNCONSTRAINED CLOCK.
    # Previously this was invisible: the port quietly joined the data ports.
    for c in cands:
        if c["port"] not in clk_names:
            holes.append({
                "kind": "clock_port_without_period", "port": c["port"],
                "detail": ("'{}' structurally drives register clock pins but no "
                           "period was supplied, so no create_clock was emitted. "
                           "It is EXCLUDED from the I/O delay population -- a "
                           "clock port given set_input_delay would be timed as a "
                           "data path while the clock itself stayed undefined."
                           .format(c["port"]))})
    for p in sorted(declared_resets & set(enum.get("inputs") or [])):
        holes.append({
            "kind": "reset_port_not_timed", "port": p,
            "detail": ("'{}' is a declared reset and was EXCLUDED from the I/O "
                       "delay population. An asynchronous reset has no "
                       "synchronous arrival time, so an input delay would invent "
                       "one. Supply an explicit exception (false_path, or a "
                       "recovery/removal budget against its clock) to constrain "
                       "it deliberately.".format(p))})

    macro_inputs = [
        p for p in (enum.get("inputs") or []) if p not in _all_clock_ports]
    macro_outputs = list(enum.get("outputs") or [])
    input_transition = intent.get("macro_input_transition_ns")
    if isinstance(input_transition, dict):
        input_transition_source = (
            input_transition.get("source")
            or "caller-supplied (no source recorded)")
        input_transition = input_transition.get("value")
    else:
        input_transition_source = (
            intent.get("macro_electrical_source")
            or "caller-supplied (no source recorded)")
    if macro_inputs:
        if input_transition is None:
            holes.append({
                "kind": "macro_input_transition_not_supplied",
                "port_count": len(macro_inputs),
                "detail": ("{} non-clock macro input port(s) exist but no input "
                           "transition was supplied. NOT EMITTED: slew is "
                           "electrical boundary intent and must not be defaulted."
                           .format(len(macro_inputs)))})
        else:
            lines.append("# macro input transition [supplied: {}]".format(
                input_transition_source))
            lines.append("# ports [derived: netlist non-clock all_inputs]")
            for p in macro_inputs:
                lines.append(
                    "set_input_transition {:.3f} [get_ports {{{}}}]".format(
                        float(input_transition), p))
            lines.append("")
            emitted.append({
                "constraint": "set_input_transition",
                "ports": len(macro_inputs), "value_ns": input_transition,
                "value_source": input_transition_source,
                "structure_basis": "netlist_non_clock_inputs"})

    output_load = intent.get("macro_output_load_pf")
    if isinstance(output_load, dict):
        output_load_source = (
            output_load.get("source")
            or "caller-supplied (no source recorded)")
        output_load = output_load.get("value")
    else:
        output_load_source = (
            intent.get("macro_electrical_source")
            or "caller-supplied (no source recorded)")
    if macro_outputs:
        if output_load is None:
            holes.append({
                "kind": "macro_output_load_not_supplied",
                "port_count": len(macro_outputs),
                "detail": ("{} macro output port(s) exist but no output load was "
                           "supplied. NOT EMITTED: load is electrical boundary "
                           "intent and must not be defaulted."
                           .format(len(macro_outputs)))})
        else:
            lines.append("# macro output load [supplied: {}]".format(
                output_load_source))
            lines.append("# ports [derived: netlist all_outputs]")
            for p in macro_outputs:
                lines.append(
                    "set_load {:.3f} [get_ports {{{}}}]".format(
                        float(output_load), p))
            lines.append("")
            emitted.append({
                "constraint": "set_load", "ports": len(macro_outputs),
                "value_pf": output_load, "value_source": output_load_source,
                "structure_basis": "netlist_outputs"})

    for kind, key, cmd in (("input", "input_delay_ns", "set_input_delay"),
                           ("output", "output_delay_ns", "set_output_delay")):
        d = intent.get(key)
        ports = enum.get("inputs" if kind == "input" else "outputs")
        if ports is None:
            continue
        if kind == "input":
            # Exclude EVERY clock-driving port, not just the ones that got a
            # period, plus every declared reset.
            io_ports = [p for p in ports
                        if p not in _all_clock_ports and p not in declared_resets]
        else:
            io_ports = [p for p in ports if p not in clk_names]
        if not io_ports:
            continue
        values = {}
        if isinstance(d, dict):
            if d.get("value") is not None:
                values["max"] = d["value"]
            if d.get("max") is not None:
                values["max"] = d["max"]
            if d.get("min") is not None:
                values["min"] = d["min"]
        if not values:
            holes.append({
                "kind": "{}_delay_not_supplied".format(kind),
                "port_count": len(io_ports),
                "detail": ("{} {} port(s) exist but no {} budget was supplied. "
                           "NOT EMITTED: an invented I/O budget silently decides "
                           "how much of the period this block may use."
                           .format(len(io_ports), kind, kind))})
            continue
        if not clk_names:
            holes.append({
                "kind": "{}_delay_has_no_clock".format(kind),
                "detail": ("an I/O delay must reference a clock, and no clock was "
                           "emitted; supply the clock period first")})
            continue
        ref = clk_names[0]
        src = d.get("source") or "caller-supplied (no source recorded)"
        lines.append("# {} delays vs '{}' [supplied: {}]".format(
            kind, ref, src))
        lines.append("# ports [derived: netlist all_{}s]".format(kind))
        for p in io_ports:
            for delay_kind in ("max", "min"):
                if delay_kind not in values:
                    continue
                lines.append(
                    "{c} -clock {r} -{k} {v:.3f} [get_ports {{{p}}}]".format(
                        c=cmd, r=ref, k=delay_kind,
                        v=float(values[delay_kind]), p=p))
        lines.append("")
        emitted.append({"constraint": cmd, "ports": len(io_ports),
                        "values_ns": values, "value_source": src,
                        "clock": ref, "structure_basis": "netlist"})

    # False paths are pure intent: nothing structural distinguishes a REQUIRED
    # exception from a wrong one. Each therefore needs a reason AND a source --
    # an unattributed exception removes paths from analysis on nobody's
    # authority, which is the one SDC defect that makes a design look better.
    for fp in (intent.get("false_paths") or []):
        reason, src = fp.get("reason"), fp.get("source")
        if not reason or not src:
            holes.append({
                "kind": "false_path_unattributed", "spec": fp,
                "detail": ("a false path was requested without a reason and a "
                           "source. NOT EMITTED: an exception REMOVES paths from "
                           "timing analysis, so an unattributed one silently "
                           "shrinks the question STA is asked.")})
            continue
        endpoints, endpoint_record, conflicts = _exception_endpoints(fp)
        if conflicts:
            holes.append({
                "kind": "exception_endpoint_ambiguous", "spec": fp,
                "detail": ("a false path supplied BOTH a port and a pin pattern "
                           "for -%s. NOT EMITTED: emitting the flag twice is "
                           "illegal SDC and choosing one for the caller would "
                           "except a path class nobody asked for."
                           % ", -".join(conflicts))})
            continue
        if not endpoints:
            holes.append({
                "kind": "exception_has_no_endpoint", "spec": fp,
                "detail": ("a false path supplied neither a -from nor a -to "
                           "endpoint. NOT EMITTED: a bare `set_false_path` "
                           "excepts EVERY path in the design, which deletes the "
                           "timing question instead of narrowing it.")})
            continue
        lines.append("# false path: {} [supplied: {}]".format(reason, src))
        lines.append(" ".join(["set_false_path"] + endpoints))
        lines.append("")
        emitted.append({"constraint": "set_false_path", "from": fp.get("from"),
                        "to": fp.get("to"), "endpoints": endpoint_record,
                        "reason": reason, "source": src})

    # Multicycle paths are also pure intent, and they RELAX timing: a wrong one
    # lets STA bless a path the silicon cannot make. Same attribution rule as a
    # false path, plus the multiplier itself, which is a number and so is never
    # defaulted. Handling this here rather than ignoring it matters: supplied
    # intent that is silently dropped leaves the caller believing a relaxation
    # was applied when the design was actually constrained as single-cycle (or,
    # worse, believing it was NOT applied when they had asked for it).
    for mc in (intent.get("multicycle_paths") or []):
        reason, src = mc.get("reason"), mc.get("source")
        mult = mc.get("multiplier")
        if not reason or not src or mult is None:
            holes.append({
                "kind": "multicycle_unattributed_or_unsupplied", "spec": mc,
                "detail": ("a multicycle path needs a multiplier, a reason and a "
                           "source; got multiplier=%r reason=%r source=%r. NOT "
                           "EMITTED: a multicycle exception RELAXES the timing "
                           "requirement, so an unattributed or invented one lets "
                           "STA sign off a path the hardware cannot meet."
                           % (mult, reason, src))})
            continue
        endpoints, endpoint_record, conflicts = _exception_endpoints(mc)
        if conflicts:
            holes.append({
                "kind": "exception_endpoint_ambiguous", "spec": mc,
                "detail": ("a multicycle path supplied BOTH a port and a pin "
                           "pattern for -%s. NOT EMITTED: emitting the flag "
                           "twice is illegal SDC and choosing one for the caller "
                           "would relax a path class nobody asked for."
                           % ", -".join(conflicts))})
            continue
        if not endpoints:
            holes.append({
                "kind": "exception_has_no_endpoint", "spec": mc,
                "detail": ("a multicycle path supplied neither a -from nor a -to "
                           "endpoint. NOT EMITTED: a bare `set_multicycle_path` "
                           "relaxes EVERY path in the design.")})
            continue
        for kind in ("setup", "hold"):
            if kind == "hold" and not mc.get("hold"):
                continue
            parts = ["set_multicycle_path", str(mult), "-" + kind] + endpoints
            lines.append("# multicycle {}x {}: {} [supplied: {}]".format(
                mult, kind, reason, src))
            lines.append(" ".join(parts))
            emitted.append({"constraint": "set_multicycle_path", "kind": kind,
                            "multiplier": mult, "from": mc.get("from"),
                            "to": mc.get("to"), "endpoints": endpoint_record,
                            "reason": reason, "source": src})
        lines.append("")

    # Case analysis ties a MODE CONTROL to a constant so a mode-specific timing
    # view can be analysed (functional-mode-only, with `scan_en` held at its
    # functional value, being the case this exists for). It is pure intent and
    # it REMOVES logic from analysis, so it carries the same attribution rule as
    # a false path, plus the constant itself -- which is a value, and is
    # therefore never defaulted. Tying the wrong control, or tying it to the
    # wrong constant, silently deletes whole path classes from STA.
    known_objects = set(enum.get("inputs") or []) | set(enum.get("outputs") or [])
    for ca in (intent.get("case_analysis") or []):
        reason, src = ca.get("reason"), ca.get("source")
        value = ca.get("value")
        port, pin = ca.get("port"), ca.get("pin")
        if port and pin:
            holes.append({
                "kind": "case_analysis_ambiguous_object", "spec": ca,
                "detail": ("a case analysis named BOTH a port and a pin. NOT "
                           "EMITTED: they are different objects and choosing "
                           "one for the caller would constant a node nobody "
                           "named.")})
            continue
        if not (port or pin) or value is None or not reason or not src:
            holes.append({
                "kind": "case_analysis_unattributed_or_unsupplied", "spec": ca,
                "detail": ("a case analysis needs an object (port or pin), a "
                           "value, a reason and a source; got port=%r pin=%r "
                           "value=%r reason=%r source=%r. NOT EMITTED: tying a "
                           "control to a constant REMOVES every path the other "
                           "value would have exercised, so an unattributed or "
                           "invented one shrinks the question STA is asked."
                           % (port, pin, value, reason, src))})
            continue
        if str(value) not in ("0", "1"):
            holes.append({
                "kind": "case_analysis_value_not_binary", "spec": ca,
                "detail": ("case-analysis value %r is not 0 or 1. NOT EMITTED: "
                           "the constant a mode control is held at is design "
                           "intent, and a value the tool cannot interpret must "
                           "not be guessed." % (value,))})
            continue
        if port and port not in known_objects:
            holes.append({
                "kind": "case_analysis_matched_no_port", "port": port,
                "detail": ("a case analysis was supplied for port '{}', but no "
                           "such port exists in the netlist. NOT EMITTED, and "
                           "NOT ignored: the caller believes this mode is tied "
                           "off and it is not.".format(port))})
            continue
        collection, pattern = (
            ("get_ports", port) if port else ("get_pins", pin))
        lines.append("# case analysis: {} [supplied: {}]".format(reason, src))
        lines.append("set_case_analysis {v} [{c} {{{p}}}]".format(
            v=int(str(value)), c=collection, p=pattern))
        lines.append("")
        emitted.append({"constraint": "set_case_analysis",
                        "object": collection, "pattern": pattern,
                        "value": int(str(value)),
                        "object_verified": bool(port),
                        "reason": reason, "source": src})

    design_rules = intent.get("design_rules") or {}
    rule_source = design_rules.get("source")
    for key, command in (
            ("max_transition_ns", "set_max_transition"),
            ("max_capacitance_pf", "set_max_capacitance"),
            ("max_fanout", "set_max_fanout")):
        if design_rules.get(key) is None:
            continue
        src = rule_source or "caller-supplied (no source recorded)"
        value = design_rules[key]
        lines.append("# {} [supplied: {}]".format(key, src))
        lines.append("{} {:.3f} [current_design]".format(
            command, float(value)))
        emitted.append({"constraint": command, "value": value,
                        "source": src})
    if design_rules:
        lines.append("")

    return lines, emitted, holes, port_classes


def verify_electrical_intent(sdc_text, enum, intent):
    """Verify every supplied electrical-intent command and resolved object."""
    intent = intent or {}
    expected = []
    clocks = derive_clock_candidates(enum)
    if clocks is None:
        return {
            "required": True, "assessable": False, "pass": False,
            "expected_commands": None,
            "missing_commands": ["design enumeration unavailable"],
        }

    for candidate in clocks:
        port = candidate["port"]
        spec = (intent.get("clocks") or {}).get(port) or {}
        transition = spec.get("transition_ns")
        if transition is None:
            transition = intent.get("clock_transition_ns")
        if isinstance(transition, dict):
            transition = transition.get("value")
        if transition is not None:
            expected.append(
                "set_clock_transition {:.3f} [get_clocks {}]".format(
                    float(transition), port))

        latency = spec.get("network_latency_pre_cts_ns")
        if latency is None:
            latency_spec = intent.get("clock_latency_ns")
            if isinstance(latency_spec, dict):
                latency = latency_spec.get("network_pre_cts")
                if latency is None:
                    latency = latency_spec.get("value")
            else:
                latency = latency_spec
        if latency is not None:
            expected.append(
                "set_clock_latency {:.3f} [get_clocks {}]".format(
                    float(latency), port))

    input_transition = intent.get("macro_input_transition_ns")
    if isinstance(input_transition, dict):
        input_transition = input_transition.get("value")
    if input_transition is not None:
        clock_ports = {c["port"] for c in clocks}
        for port in (enum.get("inputs") or []):
            if port not in clock_ports:
                expected.append(
                    "set_input_transition {:.3f} [get_ports {{{}}}]".format(
                        float(input_transition), port))

    output_load = intent.get("macro_output_load_pf")
    if isinstance(output_load, dict):
        output_load = output_load.get("value")
    if output_load is not None:
        for port in (enum.get("outputs") or []):
            expected.append(
                "set_load {:.3f} [get_ports {{{}}}]".format(
                    float(output_load), port))

    required = any(
        key in intent for key in (
            "clock_transition_ns", "clock_latency_ns",
            "macro_input_transition_ns", "macro_output_load_pf"))
    missing = [command for command in expected if command not in sdc_text]
    return {
        "required": required,
        "assessable": True,
        "pass": required and bool(expected) and not missing,
        "expected_commands": len(expected),
        "verified_commands": len(expected) - len(missing),
        "missing_commands": missing,
        "basis": "authored_sdc_exact_command_and_enumerated_object_crosscheck",
    }
