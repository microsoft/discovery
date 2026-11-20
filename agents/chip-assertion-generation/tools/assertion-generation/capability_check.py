"""Build-time capability gate for assertion authoring + checkability screening.

WHY THIS REPLACES THE OLD GATE
------------------------------
The previous gate proved the toolchain worked by running:

    always @(posedge clk) g_true: assert (1'b1);

For THIS agent that is self-refuting. `assertion_generation_utils._author_one`
classifies a property of `1'b1` as VACUOUS -- it is, verbatim, the anti-pattern
this agent exists to detect and reject in other people's assertions. The build
gate was certifying the toolchain with the very construct the tool is built to
flag.

It is also unfalsifiable. A tautology passes under a working engine, under an
engine that passes everything, and under an engine that dropped the property
before proving anything. A gate whose check cannot fail proves only that a
process exited.

WHAT THIS GATE ESTABLISHES
--------------------------
  1. The vacuity screen actually fires -- on `1'b1`, on a false antecedent, and
     on a missing operand -- and does NOT fire on a real property. A screen that
     never fires and a screen that always fires are both useless, so both
     directions are checked.
  2. `formal_checkable: true` is BACKED. The claim is only meaningful if a
     property so classified can genuinely be violated and the violation found.
     The gate translates a checkable authored property into the immediate-
     assertion encoding and proves the engine reports PASS when it holds and
     FAIL when it does not.
  3. The reverse: a VACUOUS property is shown to be undetectable by the engine
     -- it passes even when the design is broken. That is the concrete reason
     vacuity screening exists, demonstrated rather than asserted.

SCOPE, STATED PLAINLY
---------------------
The authored output is CONCURRENT SVA (`assert property (@(posedge clk) ...)`),
which open-source Yosys does not parse -- that grammar is a Verific (commercial)
feature. So `formal_checkable` is a CLASSIFICATION of whether a property is
structurally provable, not a proof that this toolchain parsed that exact text.
This gate therefore proves the underlying semantics are checkable in the
immediate encoding sby does support, and does not claim the concurrent form was
parsed.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# A 3-bit saturating counter. `y <= 5` HOLDS; `y <= 3` is VIOLATED, but only
# after several cycles, so finding it requires real temporal unrolling.
# `y` is EXPLICITLY INITIALISED: without an initial value a formal engine treats
# the start state as free, so the solver could begin at y==7 and break `y<=5`
# for reasons having nothing to do with toolchain soundness.
DESIGN = """\
module gate (input clk, input rst_n, input req, output reg [2:0] y = 3'd0);
  always @(posedge clk)
    if (!rst_n)        y <= 3'd0;
    else if (y < 3'd5) y <= y + 3'd1;
%s
endmodule
"""

# A CHECKABLE property that holds.
P_HOLDS = "  always @(posedge clk) if (rst_n) p: assert (y <= 3'd5);"
# The same shape, violated -- proves a checkable property can actually fail.
P_FAILS = "  always @(posedge clk) if (rst_n) p: assert (y <= 3'd3);"
# A VACUOUS property over the SAME broken condition. The design still violates
# `y <= 3`, but this assertion can never observe it because its guard `y > 5` is
# unreachable -- the counter saturates at 5.
#
# The guard is deliberately UNREACHABLE BY DESIGN BEHAVIOUR rather than a literal
# `1'b0`. A constant-false guard is folded away during elaboration, so the
# assertion would vanish and the run would pass with no property at all -- which
# proves nothing and is a different failure. A behaviourally unreachable guard
# survives elaboration and is proven vacuously, which is the real and much harder
# form of vacuity this screen exists to catch.
P_VACUOUS = "  always @(posedge clk) if (rst_n && y > 3'd5) p: assert (y <= 3'd3);"

SBY = """\
[options]
mode bmc
depth {depth}

[engines]
smtbmc z3

[script]
read_verilog -sv -formal gate.sv
prep -top gate

[files]
gate.sv
"""


def _bmc(work, body, depth=12):
    d = tempfile.mkdtemp(dir=work)
    with open(os.path.join(d, "gate.sv"), "w") as f:
        f.write(DESIGN % body)
    with open(os.path.join(d, "gate.sby"), "w") as f:
        f.write(SBY.format(depth=depth))
    p = subprocess.run(["sby", "-f", "gate.sby"], cwd=d,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       universal_newlines=True)
    return p.returncode, p.stdout


def main():
    failures = []

    def check(name, cond, detail=""):
        if cond:
            print("  PASS  %s" % name)
        else:
            print("  FAIL  %s  %s" % (name, detail))
            failures.append(name)

    # ---- (1) The vacuity screen, both directions -------------------------
    import assertion_generation_utils as A

    real = A._author_one({"name": "p_real", "kind": "implication",
                          "signals": {"antecedent": "req", "consequent": "gnt"}})
    check("a real implication is NOT flagged vacuous",
          not real["vacuous"] and real["formal_checkable"],
          repr(real))

    taut = A._author_one({"name": "p_taut", "kind": "sequence",
                          "signals": {"expr": "1'b1"}})
    check("1'b1 -- the OLD GATE'S OWN PROPERTY -- is flagged vacuous",
          taut["vacuous"] and not taut["formal_checkable"],
          "the previous build gate certified the toolchain with this exact "
          "construct: " + repr(taut))

    false_ant = A._author_one({"name": "p_false", "kind": "implication",
                               "signals": {"antecedent": "1'b0",
                                           "consequent": "gnt"}})
    check("an implication with a false antecedent is flagged vacuous",
          false_ant["vacuous"] and not false_ant["formal_checkable"])

    true_cons = A._author_one({"name": "p_tc", "kind": "implication",
                               "signals": {"antecedent": "req",
                                           "consequent": "1'b1"}})
    check("an implication with a tautological consequent is flagged vacuous",
          true_cons["vacuous"] and not true_cons["formal_checkable"])

    missing = A._author_one({"name": "p_miss", "kind": "onehot",
                             "signals": {}})
    check("a property with a missing operand is flagged vacuous",
          missing["vacuous"] and not missing["formal_checkable"])

    # ---- (2) Is `formal_checkable` BACKED by the engine? ------------------
    for tool in ("sby", "yosys", "yosys-smtbmc", "z3"):
        if not shutil.which(tool):
            print("  FAIL  %s not on PATH" % tool)
            failures.append(tool)
    if any(f in ("sby", "yosys", "yosys-smtbmc", "z3") for f in failures):
        print("TOOLCHAIN MISSING")
        return 1

    work = tempfile.mkdtemp()

    rc, out = _bmc(work, P_HOLDS)
    check("a checkable property that holds is reported PASS",
          rc == 0 and re.search(r"DONE \(PASS", out), "rc=%d" % rc)

    rc, out = _bmc(work, P_FAILS)
    # The engine's own "DONE (FAIL)" is required -- NOT `rc != 0`. A crashed or
    # sabotaged engine also exits non-zero, so the return code would let a
    # broken toolchain satisfy the check that backs the `formal_checkable`
    # claim. (Measured on the sibling formal gate: an always-pass stub made the
    # `or rc != 0` form report PASS while nothing had been proved.)
    check("a checkable property that is violated is reported FAIL",
          bool(re.search(r"DONE \(FAIL", out)),
          "the engine cannot report a violation (rc=%d), so 'formal_checkable' "
          "would be an unbacked claim" % rc)

    # ---- (3) Demonstrate WHY vacuity screening exists ---------------------
    # Same broken design, same intended property, antecedent never true. It
    # passes. This is the failure mode the screen prevents, shown rather than
    # asserted.
    rc, out = _bmc(work, P_VACUOUS)
    check("a VACUOUS property passes on a design that is genuinely broken",
          rc == 0 and re.search(r"DONE \(PASS", out),
          "expected the vacuous property to pass vacuously; if it failed, this "
          "demonstration is no longer valid and should be re-derived")

    print()
    if failures:
        print("ASSERTION CAPABILITY GATE FAILED: %s" % ", ".join(failures))
        return 1
    with open("/opt/.formal_ok", "w") as f:
        f.write("ASSERTION_TOOLCHAIN_OK vacuity-screened bidirectional\n")
    print("ASSERTION CAPABILITY GATE PASSED "
          "(vacuity screen fires both ways; checkability is engine-backed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
