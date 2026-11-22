"""Build-time capability gate for the BMC engine. Bidirectional, so it can fail.

WHY THIS REPLACES THE OLD GATE
------------------------------
The previous gate built one module and ran one property:

    always @(posedge clk) g_true: assert (1'b1);

then treated `sby` exiting 0 as proof the formal toolchain worked. It is not.
`PASS` is the outcome of ALL of these:

  * a working solver that correctly found no counterexample;
  * a solver that cannot find counterexamples at all (everything "passes");
  * an assertion silently OPTIMIZED AWAY by `prep`, so the model it proved
    contained no property whatsoever -- an empty proof obligation is trivially
    discharged;
  * a front end that parsed the property, dropped it, and warned on stderr.

A tautology is unfalsifiable BY CONSTRUCTION, so a gate built on one cannot
distinguish a working engine from an engine that does nothing. It is the exact
defect this agent exists to detect in other people's assertions.

WHAT A REAL GATE REQUIRES
-------------------------
MEASURED on this toolchain: a design containing NO PROPERTY AT ALL exits 0,
reports `DONE (PASS)`, and even logs "Checking assertions in step N.." for every
step -- indistinguishable from a genuine proof. So a passing run is not evidence
that anything was checked.

The only construct that cannot be faked by a broken or empty flow is a
VIOLATION, so the gate is built around one:

  0. A design with NO property -> confirm it still PASSes, establishing that
     PASS carries no information (asserted, not assumed, so the rationale
     cannot silently rot).
  1. A property that MUST HOLD  -> expect PASS   (rejects a tool that fails
     everything, which would otherwise look maximally "safe")
  2. A property that MUST FAIL  -> expect FAIL, with a counterexample trace.
     THE LOAD-BEARING CHECK: a dropped, optimized-away or never-parsed
     assertion CANNOT produce a counterexample, so this is simultaneously the
     proof that properties reach the solver.
  3. The violation must NOT be reported at a depth too shallow to reach it,
     proving the engine really unrolls time rather than pattern-matching text.

Exit non-zero on any shortfall: the image must not build if formal is unsound.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

GATE_DIR = "/opt/gatecheck"

# A 3-bit counter that saturates at 5. The invariant "y <= 5" HOLDS. The
# invariant "y <= 3" is VIOLATED, but only after the counter has been let run
# for four cycles -- so finding it requires genuine temporal unrolling and
# cannot be answered from the property text alone.
#
# `y` IS EXPLICITLY INITIALISED. Without an initial value a formal engine treats
# the register's start state as FREE, so the solver may begin at y==7 and "y<=5"
# fails at step 0 -- the gate would then fail for a reason that has nothing to do
# with the toolchain being sound. An uninitialised register in a formal harness
# is a bug in the harness, not evidence about the engine.
DESIGN = """\
module gate (input clk, input rst_n, output reg [2:0] y = 3'd0);
  always @(posedge clk)
    if (!rst_n)      y <= 3'd0;
    else if (y < 3'd5) y <= y + 3'd1;
%s
endmodule
"""

HOLDS = "  always @(posedge clk) if (rst_n) p_holds: assert (y <= 3'd5);"
FAILS = "  always @(posedge clk) if (rst_n) p_fails: assert (y <= 3'd3);"
# NO PROPERTY AT ALL. The empty-obligation control -- see main().
NONE = ""

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


def _run(cmd, cwd):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True)
    return p.returncode, p.stdout


def _bmc(workdir, body, depth):
    """Run one BMC. Returns (rc, output)."""
    d = tempfile.mkdtemp(dir=workdir)
    with open(os.path.join(d, "gate.sv"), "w") as f:
        f.write(DESIGN % body)
    with open(os.path.join(d, "gate.sby"), "w") as f:
        f.write(SBY.format(depth=depth))
    return _run(["sby", "-f", "gate.sby"], d)


def main():
    failures = []

    def check(name, cond, detail=""):
        if cond:
            print("  PASS  %s" % name)
        else:
            print("  FAIL  %s  %s" % (name, detail))
            failures.append(name)

    for tool in ("sby", "yosys", "yosys-smtbmc", "z3"):
        if not shutil.which(tool):
            print("  FAIL  %s not on PATH" % tool)
            failures.append(tool)
    if failures:
        print("TOOLCHAIN MISSING")
        return 1

    work = tempfile.mkdtemp()

    # (0) EMPTY-OBLIGATION CONTROL. MEASURED on this toolchain (Yosys 0.68+130,
    # sby, z3): a design containing NO PROPERTY WHATSOEVER still exits 0, still
    # reports DONE (PASS), and its log still prints "Checking assertions in step
    # N.." for every step -- identical in every respect to a run that really
    # proved something.
    #
    # So neither the exit code NOR the log text distinguishes "proved" from
    # "there was nothing to prove". That is precisely why the old
    # `assert (1'b1)` gate certified nothing, and why the FAIL direction below
    # is the only load-bearing evidence in this file. This control is asserted
    # rather than merely commented so that if a future sby ever starts
    # rejecting empty obligations, this gate fails and the reasoning above gets
    # revisited instead of silently rotting.
    rc, out = _bmc(work, NONE, 12)
    check("control: a design with NO property still reports PASS "
          "(so PASS alone proves nothing)",
          rc == 0 and re.search(r"DONE \(PASS", out),
          "empty obligation did NOT pass; the rationale for this gate's "
          "structure has changed and must be re-derived")

    # (1) TRUE property must PASS. Guards against a tool that fails everything.
    rc, out = _bmc(work, HOLDS, 12)
    check("true property (y <= 5) reported PASS",
          rc == 0 and re.search(r"DONE \(PASS", out),
          "rc=%d" % rc)

    # (2) FALSE property must FAIL. THE LOAD-BEARING CHECK, and -- per (0) --
    # the ONLY one that proves the property reached the solver at all: a
    # dropped or optimized-away assertion cannot produce a counterexample.
    # A formal gate that cannot report a violation launders unverified logic
    # into signoff.
    rc, out = _bmc(work, FAILS, 12)
    # The verdict must be the ENGINE'S OWN "DONE (FAIL)", never `rc != 0`.
    # A crashed, mis-configured or sabotaged engine also exits non-zero, so
    # accepting the return code would let a BROKEN toolchain satisfy the one
    # check that carries all the weight. MEASURED: with an always-pass solver
    # stubbed in, `or rc != 0` reported this check as PASS while the engine had
    # proved nothing at all.
    check("false property (y <= 3) reported FAIL",
          bool(re.search(r"DONE \(FAIL", out)),
          "engine did NOT report a violation (rc=%d) -- it cannot fail, so a "
          "pass from it means nothing" % rc)

    # A failure is only useful with evidence of WHY.
    check("counterexample trace produced for the false property",
          bool(re.search(r"Assert failed in gate|counterexample|\.vcd", out, re.I)),
          "reported FAIL with no counterexample")

    # (3) Depth handling: the violation needs 5 steps to reach y==4. At depth 2
    # the engine must NOT report it. A tool that "finds" it at depth 2 is
    # matching text, not unrolling time. The run must also genuinely COMPLETE:
    # an engine that crashed trivially "does not report" the violation, which
    # would otherwise satisfy this check for entirely the wrong reason.
    rc, out = _bmc(work, FAILS, 2)
    check("shallow depth does not report the deep violation",
          rc == 0 and bool(re.search(r"DONE \(PASS", out)),
          "expected a clean PASS within the shallow bound; got rc=%d" % rc)

    print()
    if failures:
        print("FORMAL CAPABILITY GATE FAILED: %s" % ", ".join(failures))
        return 1
    os.makedirs(GATE_DIR, exist_ok=True)
    with open("/opt/.formal_ok", "w") as f:
        f.write("FORMAL_TOOLCHAIN_OK bidirectional\n")
    print("FORMAL CAPABILITY GATE PASSED (proves PASS *and* FAIL)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
