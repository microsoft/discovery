#!/usr/bin/env python3
"""mutation.py -- conservative source-level Verilog mutation for TESTBENCH
NON-VACUITY proof.

WHY THIS EXISTS
---------------
A testbench that passes tells you nothing unless you know it is capable of
failing. A scoreboard whose compare was commented out, a sequence that never
drives the DUT, an `assert` behind a condition that is never true -- all of
these report PASS forever, and every downstream gate believes them.

The only way to know is to break the design on purpose and check that the
testbench notices. This module generates those deliberate breakages.

PRIOR ART IN THIS REPO. bsum16 simulation.2 did exactly this BY HAND: a
one-line mutant (`sum + {8'h00, data}` -> `... + 16'h0001`) was simulated as a
"negative control / non-vacuity proof" and produced 1226 MISMATCH lines
(TESTS=8 PASS=7 FAIL=1). It worked, it was recorded under reports/diagnostics/,
and NO TOOL SUPPORTED IT -- so it happened once, on one design, because a human
thought of it. This module makes that repeatable.

WHY SOURCE-LEVEL AND NOT `yosys mutate`
---------------------------------------
`yosys mutate` is the better engine and I verified it round-trips
(read_verilog -> prep -> mutate -> write_verilog -> iverilog compiles cleanly,
measured on the real bsum16.v). But yosys and the simulator/cocotb stack are in
DIFFERENT images: chip-testbench-uvm-generation and chip-functional-verification
carry cocotb+iverilog+verilator and no yosys, while chip-formal-verification and
chip-lec carry yosys and no cocotb. Mutating requires the design AND the
testbench in one process, so source-level mutation is what can actually run
here. The operator set below is therefore deliberately narrow and paranoid.

SAFETY RULES (each one exists because the naive version is wrong)
----------------------------------------------------------------
* Comments and string literals are MASKED before candidates are located, so a
  `+` inside `// sum + 1` or `$display("a+b")` is never mutated.
* `<`, `>`, `=` are NEVER touched. Mutating them risks corrupting `<=`, which
  in Verilog is BOTH "less-or-equal" AND non-blocking assignment; turning an
  assignment into a comparison produces silent nonsense.
* `+:` and `-:` (Verilog-2001 indexed part-select) are excluded -- mutating the
  `+` in `[base +: width]` is a syntax error, not a defect.
* `->` (event trigger) is excluded so its `-` is not mutated.
* `^~` and `~^` (XNOR) are excluded so their `^` is not mutated.
* `&&`/`||` are matched BEFORE `&`/`|` so a two-character operator is never
  half-mutated into garbage.

EQUIVALENT MUTANTS. A mutant that survives is NOT proof of a testbench defect:
it may be semantically equivalent to the original (mutating genuinely dead
logic). This module never claims otherwise -- it reports what changed and lets
the caller triage. What IS provable is the opposite direction: a testbench that
kills nothing across many real mutants is not checking anything.
"""
import re

__all__ = ["mask_noncode", "find_candidates", "apply_candidate", "generate"]

# --- masking ---------------------------------------------------------------

_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_STRING = re.compile(r'"(?:\\.|[^"\\\n])*"')


def mask_noncode(src):
    """Return `src` with comments and string literals replaced by spaces.

    Same length as the input, so offsets found in the mask apply directly to
    the original text. Newlines are preserved so line numbers stay correct.
    """
    out = list(src)

    def blank(m):
        for i in range(m.start(), m.end()):
            if out[i] != "\n":
                out[i] = " "

    for rx in (_BLOCK_COMMENT, _LINE_COMMENT, _STRING):
        for m in rx.finditer("".join(out)):
            blank(m)
    return "".join(out)


# --- operator mutation -----------------------------------------------------
#
# Ordered longest-first so `&&` is considered before `&`. Each entry is
# (regex, replacement, human-readable operator name).
_OPS = [
    (re.compile(r"&&"), "||", "&&"),
    (re.compile(r"\|\|"), "&&", "||"),
    (re.compile(r"=="), "!=", "=="),
    (re.compile(r"!="), "==", "!="),
    # A binary/unary + that is NOT part of `+:`.
    (re.compile(r"\+(?![:+=])"), "-", "+"),
    # A - that is NOT part of `-:` or `->`.
    (re.compile(r"-(?![:>\-=])"), "+", "-"),
    # A ^ that is NOT part of `^~`, and not preceded by `~` (i.e. `~^`).
    (re.compile(r"(?<!~)\^(?!~)"), "&", "^"),
]

# A sized literal: 16'h00ff, 8'b1010, 4'd7, with optional _ separators.
_LITERAL = re.compile(r"(\d+)'([hHdDbBoO])([0-9a-fA-F_xXzZ?]+)")
_BASE = {"h": 16, "d": 10, "b": 2, "o": 8}


def _mutate_literal(m):
    """Increment a sized literal by 1, wrapping within its declared width.

    Returns None for literals containing x/z/? -- those are not numbers and
    incrementing them would be a syntax error, not a defect.
    """
    width, base_c, digits = m.group(1), m.group(2).lower(), m.group(3)
    clean = digits.replace("_", "")
    if re.search(r"[xXzZ?]", clean):
        return None
    try:
        val = int(clean, _BASE[base_c])
        w = int(width)
    except (ValueError, KeyError):
        return None
    if w <= 0 or w > 4096:
        return None
    new = (val + 1) % (1 << w)
    # `format()`, not %-formatting: Python has no "%b" conversion, so the
    # obvious `"%b" % v` raises ValueError on every binary literal and takes
    # the whole run down. Caught by running this against the real crc16_ccitt.v,
    # which contains 16'b... literals that bsum16.v does not.
    conv = {"h": "x", "d": "d", "b": "b", "o": "o"}[base_c]
    text = format(new, conv)
    # Preserve the written digit count so 8'h00 becomes 8'h01, not 8'h1. Same
    # value either way, but a minimal textual diff keeps the mutant readable
    # and reviewable next to the original.
    text = text.rjust(len(clean), "0")
    return "%s'%s%s" % (width, m.group(2), text)


def find_candidates(src):
    """Every mutation site in `src`, as dicts with absolute offsets.

    Located against the MASKED text so comments and strings are excluded, but
    the offsets are valid in the original.
    """
    masked = mask_noncode(src)
    out = []
    for rx, repl, name in _OPS:
        for m in rx.finditer(masked):
            out.append({"kind": "operator", "op": name, "to": repl,
                        "start": m.start(), "end": m.end(),
                        "line": masked.count("\n", 0, m.start()) + 1})
    for m in _LITERAL.finditer(masked):
        new = _mutate_literal(m)
        if new is None:
            continue
        out.append({"kind": "literal", "op": m.group(0), "to": new,
                    "start": m.start(), "end": m.end(),
                    "line": masked.count("\n", 0, m.start()) + 1})
    out.sort(key=lambda c: c["start"])
    return out


def apply_candidate(src, cand):
    """Apply ONE candidate, returning (mutated_source, description)."""
    before = src[cand["start"]:cand["end"]]
    mutated = src[:cand["start"]] + cand["to"] + src[cand["end"]:]
    desc = "line %d: %s -> %s (%s)" % (cand["line"], before, cand["to"],
                                       cand["kind"])
    return mutated, desc


def generate(src, limit=8, seed=0):
    """Up to `limit` single-site mutants, EVENLY SPREAD across the file.

    Even spreading matters: candidates are offset-sorted, so taking the first N
    would cluster every mutant in the first few lines and measure only whether
    the testbench exercises the top of the file. `seed` shifts the sampling
    phase so repeat runs can probe different sites deterministically.
    """
    cands = find_candidates(src)
    if not cands or limit <= 0:
        return []
    n = min(limit, len(cands))
    step = len(cands) / float(n)
    picked, seen = [], set()
    for i in range(n):
        idx = int((i + 0.5) * step + seed) % len(cands)
        while idx in seen:
            idx = (idx + 1) % len(cands)
        seen.add(idx)
        picked.append(cands[idx])
    picked.sort(key=lambda c: c["start"])
    out = []
    for i, c in enumerate(picked):
        mut, desc = apply_candidate(src, c)
        out.append({"index": i, "source": mut, "description": desc,
                    "line": c["line"], "kind": c["kind"],
                    "from": src[c["start"]:c["end"]], "to": c["to"]})
    return out
