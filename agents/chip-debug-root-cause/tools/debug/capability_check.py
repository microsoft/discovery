"""Build-time capability gate for the chip-debug tool. NON-VACUOUS BY DESIGN.

Run during `podman build`; a non-zero exit fails the build.

The defects this tool was fixed for were claims that had never been executed
(waveform analysis that parsed nothing, a `reduce` that reduced nothing, and
determinism asserted from the presence of a seed field). A gate that merely
imported the modules would repeat exactly that mistake, so every check below
exercises a real capability against an input whose answer is known in advance --
including the NEGATIVE cases, because a checker that cannot fail proves nothing.
"""

import os
import sys
import tempfile

sys.path.insert(0, "/app")

import reproducer  # noqa: E402
import vcd_reader  # noqa: E402

# Use THIS interpreter rather than a bare `python3`, so the gate exercises the
# same code paths wherever it runs. A hard-coded `python3` silently became a
# not-found command off-container -- which is precisely the condition check 6b
# now asserts on deliberately.
_PY = sys.executable or "python3"

_VCD = """$timescale 1ns $end
$scope module tb $end
$var wire 1 ! clk $end
$var wire 4 @ data [3:0] $end
$var wire 1 # tie $end
$upscope $end
$enddefinitions $end
#0
0!
b0000 @
1#
#10
1!
bxx01 @
#20
0!
"""


def main():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.vcd")
    with open(p, "w") as fh:
        fh.write(_VCD)

    # 1. A KNOWN X must be located at the right signal and the right time.
    w = vcd_reader.read(p)
    xs = vcd_reader.find_x_states(w, settle_time=1)
    assert len(xs) == 1, "expected exactly one X signal, got %r" % (xs,)
    assert xs[0]["signal"] == "tb.data[3:0]", xs
    assert xs[0]["time"] == 10, xs

    # 2. settle_time must actually exclude pre-reset X (else the feature is a lie).
    assert vcd_reader.find_x_states(w, settle_time=50) == []

    # 3. A constant signal must be reported stuck; a toggling one must not.
    stuck = {s["signal"] for s in vcd_reader.find_stuck_signals(w)}
    assert "tb.tie" in stuck and "tb.clk" not in stuck, stuck

    # 4. An unreadable trace must RAISE -- never return an empty "clean" result.
    for bad in (os.path.join(d, "nope.vcd"), None):
        try:
            vcd_reader.read(bad)
        except vcd_reader.VcdUnavailable:
            pass
        else:
            raise AssertionError("unreadable trace did not raise: %r" % (bad,))

    # 5. Determinism with no command is UNKNOWN, never True.
    r = reproducer.check_determinism(None)
    assert r["assessable"] is False and r["deterministic"] is None, r

    # 6. A genuinely non-deterministic command must be CAUGHT.
    nd = reproducer.check_determinism(
        '"%s" -c "import random; print(random.random())"' % _PY, runs=3)
    assert nd["deterministic"] is False, nd

    # 6b. A command that CANNOT RUN must be not_assessable, never deterministic.
    # Identical failures to launch agree perfectly, so without the guard in
    # _did_not_execute they were reported as a reliably reproducing test.
    gone = reproducer.check_determinism(
        "definitely-not-a-real-command-xyzzy --go", runs=2)
    assert gone["assessable"] is False and gone["deterministic"] is None, gone

    # 7. A deterministic command must agree across runs.
    ok = reproducer.check_determinism('"%s" -c "print(42)"' % _PY, runs=3)
    assert ok["deterministic"] is True, ok

    # 8. ddmin must really minimise: only the presence of 7 causes the failure.
    mini, st = reproducer.ddmin(list(range(1, 21)), lambda s: 7 in s)
    assert mini == [7], (mini, st)

    # 9. ddmin must refuse when the failure is absent from the full input.
    none_res, st2 = reproducer.ddmin([1, 2, 3], lambda s: False)
    assert none_res is None and st2.get("reduced") is False, (none_res, st2)

    print("DEBUG_CAPABILITY_OK")


if __name__ == "__main__":
    main()
