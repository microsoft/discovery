"""Dependency-free VCD (Value Change Dump) reader for root-cause triage.

WHY THIS EXISTS
---------------
The agent's description claimed it "drives waveform/trace analysis". It did not:
the only occurrence of the word `waveform` in the whole tool was inside a
hypothesis string telling the USER to go and inspect one. Every hypothesis was
a regex over a log message. This module makes the claim true by reading the
waveform the simulator actually produced.

WHY NO LIBRARY
--------------
The tool image is `debian:12-slim` with bare `python3` and no pip index, so
`pyvcd`/`vcdvcd` are not available. VCD is a small, stable, well-specified text
format (IEEE 1364), so it is parsed here directly rather than adding a network
dependency to a debug container.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
FST is NOT supported. FST is a compressed binary format and cannot be read
without the GTKWave reader; a partial implementation would be worse than none,
because it would return plausible-looking wrong values. `read()` refuses an FST
file by extension and magic bytes and returns `not_assessable` -- it never
silently returns an empty result set that a caller could mistake for "clean".

THE CENTRAL RULE, SAME AS EVERY OTHER GATE IN THIS CATALOG
----------------------------------------------------------
A waveform that could not be read is NOT a waveform with no problems in it.
Every accessor returns None (never 0, never []) when the trace is unavailable
or unparsable, and the caller must render that as `not_assessable`.
"""

import os
import re

# Values that mean "this signal is not carrying a defined logic level".
# 'x'/'X' is unknown; 'z'/'Z' is high-impedance. They are tracked separately:
# an X is usually an uninitialised or contended state (a real bug), while a Z on
# a tristate bus can be entirely correct, so conflating them would manufacture
# false positives on exactly the designs that use buses legitimately.
_X_CHARS = set("xX")
_Z_CHARS = set("zZ")

_TS_RE = re.compile(r"(\d+)\s*([munpf]?s)")

# Relative magnitude of each time unit, used ONLY to convert a tick count into a
# human-readable time. Timing decisions are never made on these.
_TS_SCALE = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12,
             "fs": 1e-15}


class VcdUnavailable(Exception):
    """Raised when a trace cannot be read. NEVER caught and turned into 'clean'."""


def _is_fst(path):
    """FST detection by extension AND magic, because a mis-named file is common."""
    if str(path).lower().endswith((".fst", ".fst.gz")):
        return True
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
        # FST blocks start with a block type byte followed by a big-endian
        # section length; a VCD always begins with '$' or whitespace/'#'.
        return bool(head) and head[:1] not in (b"$", b"#", b" ", b"\t", b"\n", b"\r")
    except OSError:
        return False


def _parse_timescale(text):
    m = _TS_RE.search(text or "")
    if not m:
        return None, None
    return int(m.group(1)), m.group(2)


def read(path, max_bytes=256 * 1024 * 1024):
    """Parse a VCD into {signals, changes, timescale, ...}.

    Raises VcdUnavailable for anything it cannot honestly read. Callers MUST let
    that surface as not_assessable rather than substituting an empty result.
    """
    if not path:
        raise VcdUnavailable("no waveform path supplied")
    if not os.path.exists(path):
        raise VcdUnavailable("waveform not found: %s" % path)
    size = os.path.getsize(path)
    if size == 0:
        raise VcdUnavailable(
            "waveform is empty (0 bytes): the simulator produced no value "
            "changes, which is a MISSING trace, not a clean one")
    if size > max_bytes:
        raise VcdUnavailable(
            "waveform is %d bytes, above the %d-byte cap; refusing a partial "
            "parse because a truncated trace silently hides later events"
            % (size, max_bytes))
    if _is_fst(path):
        raise VcdUnavailable(
            "file looks like FST (binary). FST needs the GTKWave reader and is "
            "NOT supported; re-dump as VCD ($dumpfile/-fst off). Refusing to "
            "guess at binary contents")

    # id_code -> {"name", "width", "scope"}
    signals = {}
    # id_code -> [(time, value_string), ...]
    changes = {}
    scope = []
    in_defs = True
    ts_num = ts_unit = None
    now = 0
    max_time = 0
    saw_enddefinitions = False

    with open(path, "r", errors="replace") as fh:
        pending = None          # multi-line $var/$timescale accumulation
        for raw in fh:
            line = raw.strip()
            if not line:
                continue

            if in_defs:
                if pending is not None:
                    pending += " " + line
                    if "$end" not in line:
                        continue
                    chunk, pending = pending, None
                elif line.startswith("$"):
                    kw = line.split(None, 1)[0]
                    if kw in ("$var", "$timescale", "$scope", "$upscope"):
                        if "$end" not in line:
                            pending = line
                            continue
                        chunk = line
                    elif kw == "$enddefinitions":
                        in_defs = False
                        saw_enddefinitions = True
                        continue
                    elif kw in ("$date", "$version", "$comment"):
                        if "$end" not in line:
                            pending = line
                        continue
                    else:
                        continue
                else:
                    continue

                parts = chunk.replace("$end", "").split()
                if not parts:
                    continue
                if parts[0] == "$scope" and len(parts) >= 3:
                    scope.append(parts[2])
                elif parts[0] == "$upscope":
                    if scope:
                        scope.pop()
                elif parts[0] == "$timescale":
                    ts_num, ts_unit = _parse_timescale(" ".join(parts[1:]))
                elif parts[0] == "$var" and len(parts) >= 5:
                    # $var <type> <width> <id> <name> [<bitrange>] $end
                    width, ident, name = parts[2], parts[3], parts[4]
                    if len(parts) >= 6 and parts[5].startswith("["):
                        name += parts[5]
                    try:
                        width = int(width)
                    except ValueError:
                        width = None
                    signals[ident] = {
                        "name": name, "width": width,
                        "scope": ".".join(scope),
                        "full_name": ".".join(scope + [name]) if scope else name}
                continue

            # ---- value-change section ----
            if line[0] == "#":
                try:
                    now = int(line[1:])
                except ValueError:
                    continue
                max_time = max(max_time, now)
            elif line[0] in "bB":
                bits, _, ident = line[1:].partition(" ")
                ident = ident.strip()
                if ident:
                    changes.setdefault(ident, []).append((now, bits))
            elif line[0] in "rR":
                val, _, ident = line[1:].partition(" ")
                ident = ident.strip()
                if ident:
                    changes.setdefault(ident, []).append((now, val))
            elif line[0] in "$":
                continue  # $dumpvars / $dumpoff wrappers
            else:
                # scalar: <value><id>
                val, ident = line[0], line[1:].strip()
                if ident:
                    changes.setdefault(ident, []).append((now, val))

    if not saw_enddefinitions:
        raise VcdUnavailable(
            "no $enddefinitions in file: this is not a complete VCD (truncated "
            "or still being written by the simulator)")
    if not signals:
        raise VcdUnavailable(
            "VCD header declared no signals; nothing can be concluded from it")

    return {"signals": signals, "changes": changes,
            "timescale_num": ts_num, "timescale_unit": ts_unit,
            "max_time": max_time, "path": path,
            "signal_count": len(signals),
            "change_count": sum(len(v) for v in changes.values())}


def _fmt_time(vcd, t):
    n, u = vcd.get("timescale_num"), vcd.get("timescale_unit")
    if not n or u not in _TS_SCALE:
        return "%d ticks" % t
    return "%g %s" % (t * n, u)


def find_x_states(vcd, settle_time=0, ignore=()):
    """First X (and Z) event per signal, after `settle_time`.

    `settle_time` exists for a real engineering reason, not convenience: before
    reset completes, X on uninitialised state is EXPECTED. Reporting those would
    bury the one X that matters under hundreds that are normal, and a tool whose
    output is mostly noise gets ignored -- which is the same as having no tool.
    The caller states when reset is done; the boundary is recorded in the result
    so a reader can see what was excluded rather than trusting it silently.
    """
    if vcd is None:
        return None
    ig = tuple(ignore or ())
    out = []
    for ident, seq in vcd["changes"].items():
        meta = vcd["signals"].get(ident)
        if not meta:
            continue
        name = meta["full_name"]
        if any(p in name for p in ig):
            continue
        for (t, val) in seq:
            if t < settle_time:
                continue
            chars = set(val)
            if chars & _X_CHARS:
                out.append({"signal": name, "width": meta["width"],
                            "time": t, "time_human": _fmt_time(vcd, t),
                            "value": val, "kind": "x"})
                break
            if chars & _Z_CHARS:
                out.append({"signal": name, "width": meta["width"],
                            "time": t, "time_human": _fmt_time(vcd, t),
                            "value": val, "kind": "z"})
                break
    out.sort(key=lambda r: (r["time"], r["signal"]))
    return out


def find_stuck_signals(vcd, settle_time=0):
    """Signals that never change after settle_time.

    Reported as an OBSERVATION, never as a defect: a tie-off, a configuration
    input or an unused mode pin is legitimately constant. It earns its place in
    triage because a control signal that should have toggled and did not is a
    fast route to the cause -- but the judgement belongs to the engineer.
    """
    if vcd is None:
        return None
    out = []
    for ident, meta in vcd["signals"].items():
        seq = [c for c in vcd["changes"].get(ident, []) if c[0] >= settle_time]
        vals = {v for (_, v) in seq}
        if len(vals) <= 1:
            out.append({"signal": meta["full_name"], "width": meta["width"],
                        "value": (seq[-1][1] if seq else None),
                        "changes_after_settle": len(seq)})
    out.sort(key=lambda r: r["signal"])
    return out


def value_at(vcd, signal_name, time):
    """Value of a signal at a time (last change at or before `time`).

    Returns None when the signal is unknown OR when it has no change at or
    before that time -- the two are distinguished in `reason` so a caller cannot
    read "no value yet" as "value is zero".
    """
    if vcd is None:
        return None
    for ident, meta in vcd["signals"].items():
        if meta["full_name"] == signal_name or meta["name"] == signal_name:
            seq = vcd["changes"].get(ident, [])
            last = None
            for (t, v) in seq:
                if t <= time:
                    last = (t, v)
                else:
                    break
            if last is None:
                return {"signal": signal_name, "value": None,
                        "reason": "no value change at or before t=%d" % time}
            return {"signal": signal_name, "value": last[1],
                    "at_time": last[0], "queried_time": time}
    return {"signal": signal_name, "value": None,
            "reason": "signal not present in this trace"}


def activity_window(vcd, signal_names, start, end):
    """Transitions of the named signals within [start, end].

    This is the accessor that turns a failure TIME into a set of things that
    actually moved just before it -- the single most useful waveform question in
    triage, and the one the tool previously answered by telling the user to open
    the waveform themselves.
    """
    if vcd is None:
        return None
    wanted = set(signal_names or [])
    out = []
    for ident, meta in vcd["signals"].items():
        if wanted and meta["full_name"] not in wanted and meta["name"] not in wanted:
            continue
        for (t, v) in vcd["changes"].get(ident, []):
            if start <= t <= end:
                out.append({"signal": meta["full_name"], "time": t,
                            "time_human": _fmt_time(vcd, t), "value": v})
    out.sort(key=lambda r: (r["time"], r["signal"]))
    return out


def summarize(vcd):
    """Descriptive facts about the trace, for provenance."""
    if vcd is None:
        return {"assessable": False,
                "note": "waveform not read; nothing about it is known"}
    return {"assessable": True, "path": vcd.get("path"),
            "signals": vcd["signal_count"], "value_changes": vcd["change_count"],
            "max_time": vcd["max_time"],
            "max_time_human": _fmt_time(vcd, vcd["max_time"]),
            "timescale": ("%s%s" % (vcd.get("timescale_num"),
                                    vcd.get("timescale_unit"))
                          if vcd.get("timescale_num") else None)}
