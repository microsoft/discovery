#!/usr/bin/env python3
"""Multi-clock CDC and multi-reset RDC formal harness generation."""
from decimal import Decimal, InvalidOperation
from functools import reduce
from math import gcd
import re

import cdc_formal


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_SIGNAL_REF = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*$")
_BIT_REF = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*(?:\[[0-9]+\])?$")
_PROTOCOLS = {"level", "pulse", "toggle", "gray", "handshake",
              "qualifier", "mcp", "fifo", "async_fifo", "reconvergence"}


def _ident(value, field):
    text = str(value or "")
    if not _IDENT.fullmatch(text):
        raise ValueError(f"{field} must be a simple Verilog identifier")
    return text


def _signal_ref(value, field):
    text = str(value or "")
    if not _SIGNAL_REF.fullmatch(text):
        raise ValueError(f"{field} must be a safe Verilog signal reference")
    return text


def render_input_bridge_assumptions(pairs):
    lines = ["", "`ifdef FORMAL"]
    assumptions = []
    for index, pair in enumerate(pairs or []):
        if not isinstance(pair, dict):
            raise ValueError(f"input bridge {index} must be an object")
        external = str(pair.get("external") or "")
        internal = str(pair.get("internal") or "")
        if not _BIT_REF.fullmatch(external) or not _BIT_REF.fullmatch(internal):
            raise ValueError(
                f"input bridge {index} contains an unsafe signal reference")
        lines.append(f"  always @(*) assume ({internal} == {external});")
        assumptions.append(
            f"{internal} follows {external} through hash-pinned "
            f"{pair.get('module')} instance {pair.get('instance')}")
    lines += ["`endif", ""]
    return "\n".join(lines), assumptions


def _positive_int(value, field, minimum=1, maximum=100000):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an integer")
    if number < minimum or number > maximum:
        raise ValueError(f"{field} must be in [{minimum}, {maximum}]")
    return number


def _active(signal_name, polarity):
    return f"!{signal_name}" if polarity == "active_low" else signal_name


def _period_ps(value, field, allow_zero=False):
    try:
        period = Decimal(str(value)) * 1000
    except (InvalidOperation, TypeError):
        raise ValueError(f"{field} must be numeric")
    minimum = 0 if allow_zero else 1
    if period < minimum or period != period.to_integral_value():
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(
            f"{field} must resolve to a {qualifier} integer picosecond value")
    return int(period)


def _lcm(left, right):
    return left * right // gcd(left, right)


def render_clock_model(clock_intent, require_multiple=True):
    """Constrain DUT clock inputs against one formal global-time counter."""
    clocks = list(clock_intent.values())
    if require_multiple and len(clocks) < 2:
        raise ValueError("multi-clock formal requires at least two declared clocks")
    if not clocks:
        raise ValueError("formal clock model requires at least one declared clock")
    half_periods = []
    for clock in clocks:
        period_ps = _period_ps(clock.get("period_ns"),
                               f"clock {clock.get('name')}.period_ns")
        if period_ps % 2:
            raise ValueError("multi-clock periods must have integer-picosecond half periods")
        half_periods.append(period_ps // 2)
    quantum_ps = reduce(gcd, half_periods)
    periods = [2 * (half // quantum_ps) for half in half_periods]
    if max(periods) > 4096:
        raise ValueError("clock period ratio requires more than 4096 formal ticks")
    schedule_ticks = reduce(_lcm, periods)
    if schedule_ticks > 65536:
        raise ValueError("combined clock schedule requires more than 65536 formal ticks")
    width = max(2, (max(periods) - 1).bit_length())
    tick_width = max(2, (schedule_ticks - 1).bit_length())
    lines = ["", "`ifdef FORMAL",
             "  // Explicit digital clock model; this does not model metastability.",
             f"  reg [{tick_width - 1}:0] _cdf_global_tick = 0;",
             "  always @($global_clock)",
             f"    if (_cdf_global_tick == {schedule_ticks - 1})",
             "      _cdf_global_tick <= 0;",
             "    else",
             "      _cdf_global_tick <= _cdf_global_tick + 1;"]
    assumptions = []
    metadata = {"quantum_ps": quantum_ps, "schedule_ticks": schedule_ticks,
                "clocks": {}}
    for index, (clock, period_ticks) in enumerate(zip(clocks, periods)):
        name = clock.get("name") or clock.get("id")
        port = _ident(clock.get("clock_port") or clock.get("clock"),
                      f"clock {name}.port")
        relation = clock.get("relation", "primary")
        if clock.get("must_toggle", True) is False:
            max_idle = _positive_int(clock.get("max_idle_ticks"),
                                     f"clock {name}.max_idle_ticks", 1, 4096)
            idle_width = max(1, max_idle.bit_length())
            state = f"_cdf_clock_state_{index}"
            advance = f"_cdf_clock_advance_{index}"
            idle = f"_cdf_clock_idle_{index}"
            lines += [
                f"  reg {state} = 0;",
                f"  (* anyseq *) reg {advance};",
                f"  reg [{idle_width - 1}:0] {idle} = 0;",
                f"  always @($global_clock) begin",
                f"    if ({advance}) begin {state} <= !{state}; {idle} <= 0; end",
                f"    else begin {idle} <= {idle} + 1'b1; assume ({idle} < {max_idle}); end",
                "  end",
                f"  always @($global_clock) assume ({port} == {state});",
            ]
            assumptions.append(
                f"{port} may stop but advances within {max_idle} formal ticks")
            metadata["clocks"][name] = {
                "port": port, "relation": relation, "stoppable": True,
                "max_idle_ticks": max_idle, "period_ticks": period_ticks,
            }
            continue
        phase_ticks = 0
        if clock.get("phase_ns") is not None:
            phase_ps = _period_ps(
                clock["phase_ns"], f"clock {name}.phase_ns", allow_zero=True)
            if phase_ps % quantum_ps:
                raise ValueError(f"clock {name}.phase_ns is not on the formal time grid")
            phase_ticks = (phase_ps // quantum_ps) % period_ticks
        phase_expr = str(phase_ticks)
        if relation == "asynchronous":
            phase_name = f"_cdf_phase_{index}"
            lines.append(f"  (* anyconst *) reg [{width - 1}:0] {phase_name};")
            lines.append(f"  always @(*) assume ({phase_name} < {period_ticks});")
            phase_expr = phase_name
            assumptions.append(
                f"{port} has declared period {clock['period_ns']} ns with arbitrary initial phase")
        else:
            assumptions.append(
                f"{port} has declared period {clock['period_ns']} ns and phase {phase_ticks} ticks")
        lines.append(
            f"  always @($global_clock) assume ({port} == "
            f"(((_cdf_global_tick + {phase_expr}) % {period_ticks}) < "
            f"{period_ticks // 2}));")
        metadata["clocks"][name] = {
            "port": port, "relation": relation,
            "period_ticks": period_ticks, "phase": phase_expr,
        }
    lines += ["`endif", ""]
    return "\n".join(lines), metadata, assumptions


def _property(name, clock, signal_name, kind, expr, cover_expr, obligation,
              history=1):
    checked_clock = ("$global_clock" if clock == "$global_clock"
                     else _ident(clock, f"{name}.clock"))
    return {"name": _ident(name, "property name"),
            "clock": checked_clock,
            "signal": _signal_ref(signal_name, f"{name}.signal"), "kind": kind,
            "expr": expr, "cover_expr": cover_expr,
            "obligation": obligation, "history": history}


def _require_signal(symbols, name, field, minimum_width=1, exact_width=None,
                    direction=None, producer_domain=None):
    signal_name = _signal_ref(name, field)
    if symbols is not None:
        record = symbols.get(signal_name)
        if record is None:
            raise ValueError(f"{field} '{signal_name}' is absent from the elaborated DUT")
        width = record["width"] if isinstance(record, dict) else record
        if width < minimum_width:
            raise ValueError(f"{field} '{signal_name}' must be at least {minimum_width} bits")
        if exact_width is not None and width != exact_width:
            raise ValueError(
                f"{field} '{signal_name}' width {width} does not match {exact_width}")
        if direction and (not isinstance(record, dict)
                          or record.get("direction") != direction):
            raise ValueError(f"{field} '{signal_name}' must be a top-level {direction} port")
        if producer_domain and (not isinstance(record, dict)
                                or producer_domain not in
                                record.get("producer_domains", set())):
            raise ValueError(
                f"{field} '{signal_name}' is not produced in declared domain "
                f"{producer_domain}")
    return signal_name


def build_cdc_properties(crossings, clock_intent, signal_symbols=None):
    props, skipped = [], []
    for index, crossing in enumerate(crossings or []):
        if not isinstance(crossing, dict):
            skipped.append({"index": index, "reason": "formal crossing is not an object"})
            continue
        try:
            ident = _ident(crossing.get("id") or f"crossing_{index}", "crossing id")
            protocol = str(crossing.get("protocol", "")).lower()
            if protocol not in _PROTOCOLS:
                raise ValueError(f"crossing {ident} has unsupported protocol {protocol!r}")
            source_domain = crossing.get("source_domain")
            destination_domain = crossing.get("destination_domain")
            source_clock = _ident(clock_intent[source_domain]["clock_port"],
                                  f"crossing {ident}.source_clock")
            destination_clock = _ident(clock_intent[destination_domain]["clock_port"],
                                       f"crossing {ident}.destination_clock")
            minimum_width = 2 if protocol in ("gray", "fifo", "async_fifo",
                                               "reconvergence") else 1
            source = _require_signal(
                signal_symbols, crossing.get("source_signal"),
                f"crossing {ident}.source_signal", minimum_width,
                producer_domain=(None if crossing.get("primary_input") is True
                                 else source_domain))
            destination = crossing.get("destination_signal")
            destination = (_require_signal(
                signal_symbols, destination, f"crossing {ident}.destination_signal")
                           if destination else None)
            if destination and signal_symbols is not None:
                _require_signal(
                    signal_symbols, destination,
                    f"crossing {ident}.destination_signal",
                    producer_domain=destination_domain)
            latency = _positive_int(crossing.get("max_latency_cycles", 2),
                                    f"crossing {ident}.max_latency_cycles", 1, 64)
            base = re.sub(r"[^A-Za-z0-9_]", "_", ident)
            if protocol == "gray":
                props.append(_property(
                    f"cdc_{base}_source_gray", source_clock, source,
                    "gray_source_one_bit_change",
                    cdc_formal._AT_MOST_ONE_BIT.format(d=source, p=f"$past({source})"),
                    f"{source} != $past({source})",
                    f"Source Gray value {source} changes by at most one bit."))
            elif protocol in ("handshake", "qualifier", "mcp"):
                qualifier = _require_signal(
                    signal_symbols,
                    crossing.get("request") or crossing.get("qualifier"),
                    f"crossing {ident}.qualifier")
                ack = crossing.get("acknowledge")
                window = qualifier
                if ack:
                    window += " && !" + _require_signal(
                        signal_symbols, ack, f"crossing {ident}.acknowledge")
                props.append(_property(
                    f"cdc_{base}_data_held", source_clock, source,
                    f"{protocol}_data_stable", f"!({window}) || $stable({source})",
                    window, f"Data {source} is stable throughout the {protocol} window."))
                live_response = crossing.get("eventual_response")
                fairness = crossing.get("fairness_signal")
                justification = crossing.get("fairness_justification")
                if any(value is not None for value in (
                        live_response, fairness, justification)):
                    if not all(isinstance(value, str) and value for value in (
                            live_response, fairness, justification)):
                        raise ValueError(
                            f"crossing {ident} liveness requires eventual_response, "
                            "fairness_signal, and fairness_justification")
                    props[-1]["live_expr"] = _require_signal(
                        signal_symbols, live_response,
                        f"crossing {ident}.eventual_response")
                    props[-1]["live_trigger"] = qualifier
                    props[-1]["fair_expr"] = _require_signal(
                        signal_symbols, fairness,
                        f"crossing {ident}.fairness_signal")
                    props[-1]["fairness_justification"] = justification
            elif protocol == "level":
                if not destination:
                    raise ValueError(f"crossing {ident} level protocol requires destination_signal")
                stable = " && ".join(
                    f"{source} == $past({source}, {step})"
                    for step in range(1, latency + 1))
                props.append(_property(
                    f"cdc_{base}_level_converges", destination_clock, destination,
                    "level_bounded_convergence", f"!({stable}) || {destination} == {source}",
                    f"{source} != $past({source})",
                    f"Stable level {source} reaches {destination} within {latency} destination edges."))
                props[-1]["history"] = latency
            elif protocol in ("pulse", "toggle"):
                if not destination:
                    raise ValueError(f"crossing {ident} {protocol} requires destination_signal")
                source_recent = " || ".join(
                    f"{source} != $past({source}, {step})"
                    for step in range(1, latency + 1))
                props.append(_property(
                    f"cdc_{base}_{protocol}_accounted", destination_clock, destination,
                    f"{protocol}_no_spurious_destination_event",
                    f"!({destination} != $past({destination})) || ({source_recent})",
                    f"{destination} != $past({destination})",
                    f"Every destination {protocol} event has a recent source event."))
            elif protocol in ("fifo", "async_fifo"):
                write_pointer = _require_signal(
                    signal_symbols, crossing.get("write_pointer") or source,
                    f"crossing {ident}.write_pointer", 2)
                read_pointer = _require_signal(
                    signal_symbols, crossing.get("read_pointer") or destination,
                    f"crossing {ident}.read_pointer", 2)
                for side, clock, pointer in (("write", source_clock, write_pointer),
                                             ("read", destination_clock, read_pointer)):
                    props.append(_property(
                        f"cdc_{base}_{side}_pointer_gray", clock, pointer,
                        "fifo_pointer_gray", cdc_formal._AT_MOST_ONE_BIT.format(
                            d=pointer, p=f"$past({pointer})"),
                        f"{pointer} != $past({pointer})",
                        f"Async FIFO {side} pointer is Gray coded."))
                for side, clock, enable_key, guard_key in (
                        ("write", source_clock, "write_enable", "full"),
                        ("read", destination_clock, "read_enable", "empty")):
                    enable = _require_signal(
                        signal_symbols, crossing.get(enable_key),
                        f"crossing {ident}.{enable_key}")
                    guard = _require_signal(
                        signal_symbols, crossing.get(guard_key),
                        f"crossing {ident}.{guard_key}")
                    props.append(_property(
                        f"cdc_{base}_no_{side}_violation", clock, enable,
                        f"fifo_no_{side}_violation", f"!({enable} && {guard})", enable,
                        f"Async FIFO never performs {side} while {guard} is asserted."))
            elif protocol == "reconvergence":
                if not destination:
                    raise ValueError(
                        f"crossing {ident} reconvergence requires destination_signal bundle")
                props.append(_property(
                    f"cdc_{base}_reconverges_coherently", destination_clock, destination,
                    "reconvergence_one_bit_change",
                    cdc_formal._AT_MOST_ONE_BIT.format(
                        d=destination, p=f"$past({destination})"),
                    f"{destination} != $past({destination})",
                    f"Declared reconvergent bundle {destination} changes coherently."))
        except (KeyError, ValueError) as exc:
            skipped.append({"id": crossing.get("id", index), "reason": str(exc)})
    return props, skipped


def build_reset_properties(reset_intent, clock_intent, signal_symbols=None):
    props, skipped, assumption_lines = [], [], []
    active_by_id = {}
    sync_by_id = {}
    for index, reset in enumerate(reset_intent.values()):
        try:
            reset_id = _ident(reset.get("id") or f"reset_{index}", "reset id")
            source = _require_signal(
                signal_symbols,
                reset.get("port") or reset.get("source_port") or reset.get("name"),
                f"reset {reset_id}.port", exact_width=1)
            synchronized = _require_signal(
                signal_symbols, reset.get("synchronized_signal"),
                f"reset {reset_id}.synchronized_signal", exact_width=1)
            polarity = reset.get("polarity")
            if polarity not in ("active_low", "active_high"):
                raise ValueError(f"reset {reset_id} requires polarity")
            destinations = reset.get("destination_domains") or []
            stages = _positive_int(reset.get("synchronizer_stages"),
                                   f"reset {reset_id}.synchronizer_stages", 1, 32)
            latency = _positive_int(reset.get("deassertion_latency_cycles"),
                                    f"reset {reset_id}.deassertion_latency_cycles", stages, 64)
            minimum = _positive_int(reset.get("minimum_assert_cycles"),
                                    f"reset {reset_id}.minimum_assert_cycles", 1, 64)
            if len(destinations) != 1:
                raise ValueError(
                    f"reset {reset_id} requires one declaration per destination domain")
            clock = _ident(clock_intent[destinations[0]]["clock_port"],
                           f"reset {reset_id}.destination_clock")
            source_active = _active(source, polarity)
            sync_active = _active(synchronized, polarity)
            active_by_id[reset_id] = source_active
            sync_by_id[reset_id] = sync_active
            props.append(_property(
                f"rdc_{reset_id}_{reset.get('assertion')}_assert", "$global_clock",
                synchronized, f"reset_{reset.get('assertion')}_assertion",
                (f"!$past({source_active}) || ({sync_active})"
                 if reset.get("assertion") == "asynchronous" else
                 f"!(!$past({sync_active}) && ({sync_active})) || $rose({clock})"),
                source_active,
                (f"Reset {reset_id} reaches the synchronized reset by the next "
                 "global formal tick after asynchronous assertion."
                 if reset.get("assertion") == "asynchronous" else
                 f"Reset {reset_id} asserts only on a {clock} edge.")))
            props.append(_property(
                f"rdc_{reset_id}_sync_release", "$global_clock", synchronized,
                "reset_synchronous_release",
                f"!($past({sync_active}) && !({sync_active})) || $rose({clock})",
                f"$past({sync_active}) && !({sync_active})",
                f"Reset {reset_id} releases only on a {clock} edge."))
            counter_limit = max(latency, minimum)
            age_width = max(1, counter_limit.bit_length())
            age = f"_rdcf_release_age_{reset_id}"
            count = f"_rdcf_assert_count_{reset_id}"
            pending = f"_rdcf_assert_pending_{reset_id}"
            seen = f"_rdcf_assert_seen_{reset_id}"
            assertion_edge = "negedge" if polarity == "active_low" else "posedge"
            monitor_event = f"posedge {clock}"
            if reset.get("assertion") == "asynchronous":
                monitor_event += f" or {assertion_edge} {source}"
            assumption_lines += [
                f"  reg [{age_width - 1}:0] {age} = 0;",
                f"  reg [{age_width - 1}:0] {count} = 0;",
                f"  reg {pending} = 0;",
                f"  reg {seen} = 0;",
                f"  always @({monitor_event}) begin",
                f"    if ({source_active}) begin",
                f"      {age} <= 0;",
                f"      {seen} <= 1;",
                "    end else begin",
                f"      if ({age} < {latency}) {age} <= {age} + 1'b1;",
                f"      if ({age} >= {latency} && !({sync_active})) {seen} <= 0;",
                "    end",
                "  end",
                "  always @($global_clock) begin",
                f"    if (!{pending} && ({source_active})) begin",
                f"      {pending} <= 1;",
                f"      {count} <= 0;",
                f"    end else if ({pending} && $rose({clock}) && "
                f"             ({source_active}) && {count} < {minimum}) begin",
                f"      {count} <= {count} + 1'b1;",
                f"    end else if ({pending} && !({source_active})) begin",
                f"      assume ({count} >= {minimum});",
                f"      {pending} <= 0;",
                "    end",
                "  end",
            ]
            props.append(_property(
                f"rdc_{reset_id}_held_for_stages", clock, synchronized,
                "reset_deassertion_latency",
                f"!({seen} && !({source_active}) && {age} < {stages}) || ({sync_active})",
                f"{seen} && !({source_active}) && {age} < {stages}",
                f"Reset {reset_id} remains asserted through {stages} destination edges."))
            props.append(_property(
                f"rdc_{reset_id}_released_by_bound", clock, synchronized,
                "reset_release_bounded",
                f"!({seen} && !({source_active}) && {age} >= {latency}) || !({sync_active})",
                f"{seen} && !({source_active}) && {age} >= {latency} && !({sync_active})",
                f"Reset {reset_id} releases after {latency} destination edges."))
            for signal_name, reset_value in (reset.get("reset_values") or {}).items():
                signal_name = _require_signal(
                    signal_symbols, signal_name, f"reset {reset_id}.reset_values")
                value_text = str(reset_value)
                if not re.fullmatch(r"[0-9]+'[bBoOdDhH][0-9a-fA-F_xXzZ]+|[0-9]+", value_text):
                    raise ValueError(f"reset {reset_id} has unsafe reset value")
                props.append(_property(
                    f"rdc_{reset_id}_{signal_name}_value", clock, signal_name,
                    "state_held_in_reset", f"!({sync_active}) || {signal_name} == {value_text}",
                    sync_active, f"{signal_name} holds its declared value during {reset_id}."))
        except (KeyError, ValueError) as exc:
            skipped.append({"id": reset.get("id", index), "reason": str(exc)})
    for reset in reset_intent.values():
        reset_id = reset.get("id")
        if reset_id not in sync_by_id:
            continue
        for dependency in reset.get("dependencies", []):
            if dependency not in sync_by_id:
                skipped.append({"id": reset_id,
                                "reason": f"unknown reset dependency {dependency}"})
                continue
            clock = clock_intent[reset["destination_domains"][0]]["clock_port"]
            props.append(_property(
                f"rdc_{reset_id}_after_{dependency}", clock,
                reset.get("synchronized_signal"), "reset_release_order",
                f"({sync_by_id[reset_id]}) || !({sync_by_id[dependency]})",
                f"!({sync_by_id[reset_id]})",
                f"Reset {reset_id} cannot release before {dependency}."))
    reset_ids = sorted(active_by_id)
    for reset_id in reset_ids:
        others_inactive = " && ".join(
            f"!({active_by_id[other]})" for other in reset_ids
            if other != reset_id) or "1'b1"
        props.append(_property(
            f"rdc_{reset_id}_alone", "$global_clock", reset_id,
            "reset_individual_scenario_cover", "1'b1",
            f"({active_by_id[reset_id]}) && ({others_inactive}) && "
            f"_rdcf_assert_seen_{reset_id}",
            f"Reset {reset_id} can assert while every other reset is inactive."))
    if reset_ids:
        all_active = " && ".join(
            f"({active_by_id[item]}) && _rdcf_assert_seen_{item}"
            for item in reset_ids)
        props.append(_property("rdc_all_resets_asserted", "$global_clock",
                               reset_ids[0], "reset_scenario_cover",
                               "1'b1", all_active, "All resets can assert together."))
    for left_index, left in enumerate(reset_ids):
        for right in reset_ids[left_index + 1:]:
            overlap = f"_rdcf_overlap_{left}_{right}"
            assumption_lines += [
                f"  reg {overlap} = 0;",
                "  always @($global_clock) begin",
                f"    if (({active_by_id[left]}) && ({active_by_id[right]})) "
                f"{overlap} <= 1;",
                f"    else if (!({active_by_id[left]}) && !({active_by_id[right]})) "
                f"{overlap} <= 0;",
                "  end",
            ]
            props.append(_property(
                f"rdc_{left}_{right}_overlap", "$global_clock",
                reset_ids[0], "reset_pairwise_overlap_cover",
                "1'b1", f"({active_by_id[left]}) && ({active_by_id[right]}) && "
                f"_rdcf_assert_seen_{left} && _rdcf_assert_seen_{right} && {overlap}",
                f"Resets {left} and {right} can overlap."))
            props.append(_property(
                f"rdc_{left}_{right}_staggered", "$global_clock",
                reset_ids[0], "reset_staggered_release_cover",
                "1'b1", f"_rdcf_assert_seen_{left} && _rdcf_assert_seen_{right} && {overlap} && "
                f"!({active_by_id[left]}) && ({active_by_id[right]})",
                f"Reset {left} can release while {right} remains asserted."))
            props.append(_property(
                f"rdc_{right}_{left}_staggered", "$global_clock",
                reset_ids[0], "reset_staggered_release_cover",
                "1'b1", f"_rdcf_assert_seen_{left} && _rdcf_assert_seen_{right} && {overlap} && "
                f"!({active_by_id[right]}) && ({active_by_id[left]})",
                f"Reset {right} can release while {left} remains asserted."))
    assumptions = ""
    if assumption_lines:
        assumptions = "\n`ifdef FORMAL\n  // Environment minimum-pulse contracts.\n"
        assumptions += "\n".join(assumption_lines) + "\n`endif\n"
    return props, skipped, assumptions


def build_synchronous_reset_properties(reset_intent, clock_intent,
                                       signal_symbols=None):
    """Prove declared synchronous resets cannot alter state off-clock."""
    props, skipped = [], []
    state_by_domain = {}
    for name, record in (signal_symbols or {}).items():
        if not isinstance(record, dict) or not record.get("state"):
            continue
        for domain in record.get("producer_domains", set()):
            if _IDENT.fullmatch(name):
                state_by_domain.setdefault(domain, []).append(name)
    for index, reset in enumerate((reset_intent or {}).values()):
        try:
            reset_id = _ident(
                reset.get("id") or f"sync_reset_{index}",
                "synchronous reset id")
            source = _require_signal(
                signal_symbols, reset.get("port"),
                f"synchronous reset {reset_id}.port", exact_width=1,
                direction="input")
            destinations = reset.get("destination_domains") or []
            if len(destinations) != 1:
                raise ValueError(
                    f"synchronous reset {reset_id} requires one destination domain")
            domain = destinations[0]
            clock = _ident(
                clock_intent[domain]["clock_port"],
                f"synchronous reset {reset_id}.destination_clock")
            states = sorted(set(state_by_domain.get(domain, [])))
            if not states:
                raise ValueError(
                    f"synchronous reset {reset_id} has no named state in "
                    f"destination domain {domain}")
            polarity = reset.get("polarity")
            if polarity not in ("active_low", "active_high"):
                raise ValueError(
                    f"synchronous reset {reset_id} requires polarity")
            stable_state = " && ".join(f"$stable({name})" for name in states)
            props.append(_property(
                f"rdc_{reset_id}_state_changes_on_clock", "$global_clock",
                source, "synchronous_reset_state_edge",
                f"$rose({clock}) || ({stable_state})",
                f"$rose({clock}) && ({_active(source, polarity)})",
                f"State in {domain} changes only on {clock}; reset "
                f"{reset_id} activation is reachable on that edge."))
            props[-1]["state_signals"] = states
        except (KeyError, ValueError) as exc:
            skipped.append({"id": reset.get("id", index), "reason": str(exc)})
    return props, skipped


def build_qualified_capture_properties(obligations, clock_intent,
                                       signal_symbols=None):
    """Encode host-held qualified buses as explicit assumptions plus covers."""
    props, skipped = [], []
    for index, obligation in enumerate(obligations or []):
        if obligation.get("kind") != "qualified_capture_bus":
            continue
        try:
            signal = _require_signal(
                signal_symbols, obligation.get("signal"),
                f"qualified capture {index}.signal",
                exact_width=_positive_int(
                    obligation.get("width"),
                    f"qualified capture {index}.width"))
            qualifier = _require_signal(
                signal_symbols, obligation.get("qualifier"),
                f"qualified capture {index}.qualifier", exact_width=1)
            domain = obligation.get("to_domain")
            clock = _ident(
                clock_intent[domain]["clock_port"],
                f"qualified capture {index}.destination_clock")
            name = re.sub(r"[^A-Za-z0-9_]", "_", signal)
            props.append(_property(
                f"cdc_{name}_host_stable", clock, signal,
                "qualified_capture_host_assumption",
                f"!({qualifier}) || $stable({signal})", qualifier,
                obligation.get("host_stability_contract")
                or f"Host holds {signal} stable while {qualifier} is asserted."))
            props[-1]["role"] = "assume"
        except (KeyError, ValueError) as exc:
            skipped.append({
                "id": obligation.get("signal", index), "reason": str(exc)})
    return props, skipped


def derive_depth(clock_model, obligations, explicit=None):
    if explicit is not None:
        return _positive_int(explicit, "formal_depth", 2, 100000)
    slowest = max(item["period_ticks"] for item in clock_model["clocks"].values())
    progress = max(item.get("max_idle_ticks", 0)
                   for item in clock_model["clocks"].values())
    latency = max([int(item.get("max_latency_cycles", 2))
                   for item in obligations or []] + [2])
    return max(20, (slowest + progress) * (latency + 3))


def run_cdc(files, top, buses, protocols, contract, config, elaborate_check,
            output_dir="/output", signal_symbols=None):
    clock_block, clock_model, assumptions = render_clock_model(
        contract.get("clock_intent") or {}, require_multiple=False)
    source_props, source_skipped = cdc_formal.build_properties(
        buses, protocols, {name: item["clock_port"]
                            for name, item in contract["clock_intent"].items()})
    for name, clock in contract["clock_intent"].items():
        _require_signal(signal_symbols, clock["clock_port"],
                        f"clock {name}.clock_port", exact_width=1,
                        direction="input")
    measured = {(bus.get("signal"), bus.get("from_domain"), bus.get("to_domain"))
                for bus in buses}
    reconciliation_skipped = []
    for crossing in contract.get("formal_crossings") or []:
        if crossing.get("primary_input") is True:
            try:
                _require_signal(
                    signal_symbols, crossing.get("source_signal"),
                    f"crossing {crossing.get('id')}.source_signal",
                    direction="input")
            except ValueError as exc:
                reconciliation_skipped.append({
                    "id": crossing.get("id"), "reason": str(exc)})
            continue
        key = (crossing.get("source_signal"), crossing.get("source_domain"),
               crossing.get("destination_domain"))
        if key not in measured:
            reconciliation_skipped.append({
                "id": crossing.get("id"),
                "reason": ("declared formal crossing does not match a measured "
                           "structural bus/domain crossing")})
    domain_props, domain_skipped = build_cdc_properties(
        contract.get("formal_crossings"), contract["clock_intent"], signal_symbols)
    reset_props, reset_skipped, reset_assumptions = build_reset_properties(
        contract.get("reset_intent") or {}, contract["clock_intent"],
        signal_symbols)
    sync_reset_props, sync_reset_skipped = build_synchronous_reset_properties(
        contract.get("synchronous_reset_intent") or {},
        contract["clock_intent"], signal_symbols)
    capture_props, capture_skipped = build_qualified_capture_properties(
        contract.get("obligations") or [], contract["clock_intent"],
        signal_symbols)
    resolved_reset_props = list(
        (config or {}).get("_resolved_reset_properties", []))
    resolved_reset_module = (config or {}).get("_resolved_reset_module")
    resolved_reset_scope = (config or {}).get(
        "_resolved_reset_scope", "top_level" if not resolved_reset_module
        else "submodule")
    local_config = dict(config or {})
    local_config["formal_depth"] = derive_depth(
        clock_model, contract.get("formal_crossings"),
        local_config.get("formal_depth"))
    bridge_block, bridge_assumptions = render_input_bridge_assumptions(
        local_config.get("_formal_input_bridge_pairs", []))
    resolved_reset_assumptions = str(
        local_config.get("_resolved_reset_assumptions", ""))
    # A resolved reset terminal is routed to exactly ONE of three fates, and
    # NONE of them is a silent drop:
    #   "submodule"  -- a dotted 'cellname.signal' terminal resolved to a
    #                   hosting module: inject there (auxiliary_properties).
    #   "top_level"  -- a bare top-level net (e.g. post-flatten, no dotted
    #                   cell-scope prefix): there is no submodule to host an
    #                   auxiliary injection, but the net is an ordinary
    #                   top-scope signal, so attach the generated properties
    #                   as REGULAR properties on the module already being
    #                   verified.
    #   "unresolved" -- a dotted terminal whose cell/module lookup still
    #                   failed: no safe attachment point exists, so the
    #                   property is recorded as an explicit SKIP with a
    #                   reason instead of vanishing.
    resolved_reset_skipped = []
    top_scope_reset_props = []
    top_scope_reset_extra = ""
    had_resolved_reset_props = bool(resolved_reset_props)
    if resolved_reset_props and resolved_reset_scope == "top_level":
        for prop in resolved_reset_props:
            try:
                _require_signal(
                    signal_symbols, prop["signal"],
                    f"resolved reset property {prop['name']}.signal")
                _require_signal(
                    signal_symbols, prop["clock"],
                    f"resolved reset property {prop['name']}.clock",
                    exact_width=1, direction="input")
                top_scope_reset_props.append(prop)
            except ValueError as exc:
                resolved_reset_skipped.append({
                    "id": prop["name"], "reason": str(exc)})
        if top_scope_reset_props:
            top_scope_reset_extra = resolved_reset_assumptions
        resolved_reset_props = []
    elif resolved_reset_props and resolved_reset_scope == "unresolved":
        resolved_reset_skipped = [
            {"id": prop["name"],
             "reason": (
                 "reset terminal resolved to a dotted cell-scope terminal "
                 "whose owning cell/module could not be identified in the "
                 "elaborated netlist; no safe attachment point exists")}
            for prop in resolved_reset_props]
        resolved_reset_props = []
    result = cdc_formal.run(
        work_dir="/workdir", files=files, top=top, module=top,
        buses=[], protocols={}, clock_of_domain={},
        elaborate_check=elaborate_check, config=local_config,
        output_dir=output_dir,
        properties=(source_props + domain_props + reset_props
                    + sync_reset_props + capture_props
                    + top_scope_reset_props),
        skipped_properties=(source_skipped + domain_skipped
                    + reconciliation_skipped + reset_skipped
                    + sync_reset_skipped + capture_skipped
                    + resolved_reset_skipped),
        extra_injection=(clock_block + reset_assumptions + bridge_block
                         + top_scope_reset_extra),
        multiclock=True, label=("cdc_multiclock"
                                if len(clock_model["clocks"]) > 1
                                else "cdc_singleclock"),
        auxiliary_properties=(
            {resolved_reset_module: resolved_reset_props}
            if resolved_reset_module and resolved_reset_props else None),
        auxiliary_extra_injection=(
            {resolved_reset_module: resolved_reset_assumptions}
            if resolved_reset_module and resolved_reset_assumptions else None))
    result["clock_model"] = clock_model
    result["environment_assumptions"] = assumptions + bridge_assumptions
    result["semantic_absences"] = []
    if (not contract.get("reset_intent")
            and not contract.get("synchronous_reset_intent")
            and not had_resolved_reset_props):
        result["semantic_absences"].append(
            "reset obligations absent: the domain map declares no reset intent")
    if not any(item.get("kind") == "qualified_capture_bus"
               for item in contract.get("obligations") or []):
        result["semantic_absences"].append(
            "qualified-capture obligations absent: the domain map declares none")
    if not any(item.get("eventual_response")
               for item in contract.get("formal_crossings") or []):
        result["semantic_absences"].append(
            "fairness/progress obligations absent: no crossing declares "
            "eventual_response plus fairness")
    result["scope_exclusions"] = [
        "analog metastability settling",
        "destination Gray samples may legally skip source states",
        "recovery/removal timing against cell-library limits",
    ]
    return result


def run_rdc(files, top, contract, config, elaborate_check,
            output_dir="/output", signal_symbols=None):
    clock_block, clock_model, assumptions = render_clock_model(
        contract.get("clock_intent") or {}, require_multiple=False)
    props, skipped, reset_assumptions = build_reset_properties(
        contract.get("reset_intent") or {}, contract.get("clock_intent") or {},
        signal_symbols)
    local_config = dict(config or {})
    reset_records = list((contract.get("reset_intent") or {}).values())
    local_config["formal_depth"] = derive_depth(
        clock_model, [{"max_latency_cycles": reset.get(
            "deassertion_latency_cycles", 2)} for reset in reset_records],
        local_config.get("formal_depth"))
    result = cdc_formal.run(
        work_dir="/workdir", files=files, top=top, module=top,
        buses=[], protocols={}, clock_of_domain={},
        elaborate_check=elaborate_check, config=local_config,
        output_dir=output_dir, properties=props, skipped_properties=skipped,
        extra_injection=clock_block + reset_assumptions,
        multiclock=True, label="rdc_multireset")
    result["clock_model"] = clock_model
    result["environment_assumptions"] = assumptions + [
        "minimum reset assertion widths are declared environment contracts"]
    result["scope_exclusions"] = [
        "analog metastability settling",
        "recovery/removal timing against cell-library limits",
        "electrical reset-tree pulse distortion",
    ]
    return result