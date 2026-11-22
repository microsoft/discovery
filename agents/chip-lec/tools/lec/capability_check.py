"""Build-time capability gate for equivalence checking. Bidirectional, so it can fail.

WHY THIS REPLACES THE OLD GATE
------------------------------
The previous gate built one module, ran `sby` on `assert (1'b1)`, and treated
exit 0 as proof the toolchain worked. Two separate problems:

  1. IT NEVER RAN EQY. This is the LEC agent: its entire job is deciding whether
     two designs are equivalent. The gate proved a BMC could discharge a
     tautology and shipped without ever asking the equivalence engine a single
     question.
  2. A tautology is unfalsifiable BY CONSTRUCTION, so even for the BMC it
     could not distinguish a working engine from one that passes everything --
     including one where the property was optimized away before the proof.

The dangerous direction for a LEC gate is specific: **an eqy that always reports
"equivalent"** would sail through any presence check, and every downstream
transformation -- synthesis, DFT insertion, CTS, ECO -- would be blessed without
ever being compared. A checker that cannot say NO is not a checker.

WHAT A REAL GATE REQUIRES
-------------------------
  1. Two designs that ARE equivalent but STRUCTURALLY DIFFERENT -> proved
     equivalent. Structural difference matters: comparing a file with itself
     would pass under a tool that merely hashes the input.
  2. Two designs differing in exactly ONE input combination -> reported NOT
     equivalent. One combination, because a checker that only notices gross
     differences will miss the single decoded case that real bugs look like.
  3. The whole-design verdict PARSER must classify both engine outputs
     correctly -- a correct engine read by a broken parser is still a wrong
     answer, and the parser is the part that decides the gate.

Exit non-zero on any shortfall: the image must not build if LEC is unsound.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

# GOLD: sum of two 2-bit inputs, behavioural.
GOLD = """\
module dut (input [1:0] a, input [1:0] b, output [2:0] y);
  assign y = a + b;
endmodule
"""

# REVISED, EQUIVALENT: the same function written as an explicit ripple-carry
# adder. Structurally unlike GOLD -- different operators, different net
# structure -- so proving these equivalent requires actual reasoning rather
# than a textual or hash comparison.
REV_EQUIV = """\
module dut (input [1:0] a, input [1:0] b, output [2:0] y);
  wire s0 = a[0] ^ b[0];
  wire c0 = a[0] & b[0];
  wire s1 = a[1] ^ b[1] ^ c0;
  wire c1 = (a[1] & b[1]) | (c0 & (a[1] ^ b[1]));
  assign y = {c1, s1, s0};
endmodule
"""

# REVISED, EQUIVALENT, WITH A LIVE PROCESS: this is the shape that reached the
# post-DFT flat adjudicator after revised-side normalization. Unlike `prep`,
# `hierarchy` does not lower the process before `equiv_make`.
REV_PROCESS_EQUIV = """\
module dut (input [1:0] a, input [1:0] b, output reg [2:0] y);
  always @* y = a + b;
endmodule
"""

# REVISED, NOT EQUIVALENT: identical to REV_EQUIV except the carry into bit 1
# is dropped for the single case a==2'b01 && b==2'b01. Exactly ONE of the 16
# input combinations differs (1+1 yields 0 instead of 2). This is what a real
# LEC escape looks like: one decoded corner, not a wholesale rewrite.
REV_BUGGY = """\
module dut (input [1:0] a, input [1:0] b, output [2:0] y);
  wire miss = (a == 2'b01) & (b == 2'b01);
  wire s0 = a[0] ^ b[0];
  wire c0 = (a[0] & b[0]) & ~miss;
  wire s1 = a[1] ^ b[1] ^ c0;
  wire c1 = (a[1] & b[1]) | (c0 & (a[1] ^ b[1]));
  assign y = {c1, s1, s0};
endmodule
"""

# NOTE: `depth` is NOT a valid key in eqy's [options] -- it belongs to the
# strategy. Supplying it there aborts with "ERROR: unknown option 'depth'"
# BEFORE any comparison runs. That failure mode is why _ran() below exists: an
# aborted run also exits non-zero, so a config error is indistinguishable from a
# detected mismatch if the gate looks only at the return code.
EQY_CFG = """\
[gold]
read_verilog -sv gold.sv
prep -top dut

[gate]
read_verilog -sv gate.sv
prep -top dut

[strategy simple]
use sat
depth 2
"""


def _run(cmd, cwd):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True)
    return p.returncode, p.stdout


def _equiv_run(work, gold, gate):
    d = tempfile.mkdtemp(dir=work)
    for name, body in (("gold.sv", gold), ("gate.sv", gate)):
        with open(os.path.join(d, name), "w") as f:
            f.write(body)
    with open(os.path.join(d, "eq.eqy"), "w") as f:
        f.write(EQY_CFG)
    return _run(["eqy", "-f", "eq.eqy"], d)


def _flat_equiv(work, gold, gate, lower=True):
    """Whole-design proof: no free partition inputs, so strictly stronger."""
    d = tempfile.mkdtemp(dir=work)
    for name, body in (("gold.sv", gold), ("gate.sv", gate)):
        with open(os.path.join(d, name), "w") as f:
            f.write(body)
    normalization = (
        "proc; memory; rename -hide w:* c:*; " if lower else "")
    script = ("read_verilog -sv gold.sv; prep -top dut; " + normalization +
              "design -stash gold; "
              "read_verilog -sv gate.sv; hierarchy -top dut; " + normalization +
              "design -stash gate; "
              "design -copy-from gold -as gold dut; "
              "design -copy-from gate -as gate dut; "
              "equiv_make gold gate equiv; prep -top equiv; "
              "equiv_simple; equiv_induct; equiv_status -assert")
    return _run(["yosys", "-p", script], d)


def _ran(out):
    """Did the comparison actually EXECUTE, or abort before comparing anything?

    An eqy that aborts on a bad config exits NON-ZERO -- exactly like an eqy that
    detected a mismatch. Treating `rc != 0` as 'not equivalent' would therefore
    turn a broken harness into a green check, which is the same class of defect
    this gate exists to remove. Reaching the partition stage is the evidence that
    two designs were really compared.
    """
    return bool(re.search(r"partition: finished|Successfully proved|"
                          r"Failed to prove", out, re.I))


# Mirrors the whole-design classification in lec_utils._equiv. A correct engine
# read by a broken parser still yields a wrong verdict, so the parser is gated.
def _classify(out):
    proven = bool(re.search(
        r"Successfully proved designs equivalent|Equivalence successfully proven|"
        r"designs are equivalent", out, re.I))
    non = bool(re.search(
        r"Failed to prove|NOT equivalent|found a difference|"
        r"designs are not equivalent|proving.*failed", out, re.I))
    if proven and not non:
        return "equivalent"
    if non and not proven:
        return "not_equivalent"
    if non and proven:
        return "ambiguous"
    return "unparsed"


def main():
    failures = []

    def check(name, cond, detail=""):
        if cond:
            print("  PASS  %s" % name)
        else:
            print("  FAIL  %s  %s" % (name, detail))
            failures.append(name)

    for tool in ("eqy", "yosys", "sby", "yosys-smtbmc", "z3"):
        if not shutil.which(tool):
            print("  FAIL  %s not on PATH" % tool)
            failures.append(tool)
    if failures:
        print("TOOLCHAIN MISSING")
        return 1

    work = tempfile.mkdtemp()

    # (1) EQUIVALENT designs, structurally different, must be PROVED equivalent.
    # Rejects a tool that reports every comparison as a mismatch -- which would
    # look "safe" while making the gate unusable and training reviewers to
    # ignore it.
    rc, out = _equiv_run(work, GOLD, REV_EQUIV)
    check("the comparison actually executed (reached partitioning)", _ran(out),
          "eqy aborted before comparing anything: " + out.strip()[-160:])
    check("structurally different but equivalent designs proved EQUIVALENT",
          rc == 0 and _classify(out) == "equivalent",
          "rc=%d verdict=%s" % (rc, _classify(out)))

    # (2) THE LOAD-BEARING CHECK. A one-combination difference must be caught.
    # An engine that cannot say NO would bless every synthesis, DFT and ECO
    # transformation without ever comparing anything.
    #
    # The verdict must come from the PARSED OUTPUT, never from `rc != 0`: an
    # aborted run also exits non-zero, so accepting the return code would let a
    # broken harness masquerade as a working mismatch detector. MEASURED: an
    # invalid [options] key did exactly that here before this was tightened --
    # this check reported PASS while eqy had never compared anything.
    rc, out = _equiv_run(work, GOLD, REV_BUGGY)
    verdict = _classify(out)
    check("the mismatch comparison actually executed", _ran(out),
          "eqy aborted: " + out.strip()[-160:])
    check("single-input-combination mismatch reported NOT EQUIVALENT",
          verdict == "not_equivalent",
          "verdict=%s -- the checker cannot say NO, so its YES means nothing"
          % verdict)
    check("mismatch verdict is unambiguous (not both proved and failed)",
          verdict != "ambiguous",
          "output matched BOTH the proved and the failed patterns")

    # (3) The stronger whole-design proof must agree in both directions. This is
    # the form lec_utils falls back to when a partitioned run fails, so its
    # soundness is load-bearing for the escape hatch, not just for this gate.
    rc_ok, _ = _flat_equiv(work, GOLD, REV_EQUIV)
    check("flat whole-design proof confirms the equivalent pair", rc_ok == 0,
          "rc=%d" % rc_ok)
    rc_bad, _ = _flat_equiv(work, GOLD, REV_BUGGY)
    check("flat whole-design proof REJECTS the buggy pair", rc_bad != 0,
          "equiv_status -assert accepted a design with a known mismatch")

    # (4) Regression for DX-229 lec-post-dft.2/.3. The revised design contains
    # a process and is prepared with `hierarchy`, matching the packaged fallback.
    # First prove the old script fails for the diagnosed reason, then require
    # symmetric process/memory lowering to make the same pair provable.
    rc_raw, out_raw = _flat_equiv(
        work, GOLD, REV_PROCESS_EQUIV, lower=False)
    check("unlowered revised process reproduces the prior equiv_make failure",
          rc_raw != 0 and bool(re.search(
              r"contains memories or processes|run 'proc' command first",
              out_raw, re.I)),
          "the regression no longer exercises the diagnosed revised-side shape")
    rc_lowered, out_lowered = _flat_equiv(
        work, GOLD, REV_PROCESS_EQUIV)
    check("process/memory lowering closes the revised-side flat proof",
          rc_lowered == 0 and
          _classify(out_lowered) == "equivalent",
          "rc=%d verdict=%s" % (
              rc_lowered, _classify(out_lowered)))

    # (5) Parser unit checks on literal engine phrasing.
    check("parser reads a whole-design proof as equivalent",
          _classify("Equivalence successfully proven!") == "equivalent")
    check("parser reads a partition failure as not equivalent",
          _classify("Failed to prove equivalence of partition sum")
          == "not_equivalent")
    # A PARTITION-level success is deliberately NOT a whole-design proof, so a
    # run that proves some partitions and fails others must read as NOT
    # equivalent -- never as equivalent, and not as merely ambiguous. Verified
    # against the real classifier: partition wording does not match the
    # whole-design patterns, which is what makes this come out correct.
    check("partial partition success plus a failure reads as NOT equivalent",
          _classify("Successfully proved equivalence of partition a\n"
                    "Failed to prove equivalence of partition b")
          == "not_equivalent",
          "a partially-proved run must never round up to equivalent")
    # A whole-design proof AND a failure in the same log is genuinely
    # contradictory; the parser must refuse rather than pick one.
    check("contradictory output is flagged ambiguous rather than resolved "
          "silently",
          _classify("Equivalence successfully proven!\n"
                    "Failed to prove equivalence of partition b") == "ambiguous")

    print()
    if failures:
        print("LEC CAPABILITY GATE FAILED: %s" % ", ".join(failures))
        return 1
    with open("/opt/.formal_ok", "w") as f:
        f.write("LEC_TOOLCHAIN_OK bidirectional\n")
    print("LEC CAPABILITY GATE PASSED (proves EQUIVALENT *and* NOT-EQUIVALENT)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
