"""Regression test for DX-146: `_reset_hygiene()` must flatten before analysis.

BACKGROUND (DX-42 / DX-146)
----------------------------
`_reset_hygiene()`'s Yosys script used to run `hierarchy -check -top {top};
proc; opt -purge; write_json` with no `flatten`. Its analyzer
(`reset_hygiene.analyze`) only inspects the cells of the TOP module. Without
flattening, a reset driven from the top module into a child instance's own
`rst_n` port is just an ordinary top-level cell connection -- not an
`$adff`/`$sdff` reset pin -- so it fell outside the ARST/SRST/CLR/SET/CLK/Q/
ALOAD exclusion set and was misclassified as `reset_used_as_data`. That
produced a false gating failure on myTop4_soc's `rst_sync_n` net (see
campaigns/mytop4-hiersoc/.../reports/REPORT.md section 5b).

This test proves two things with REAL yosys elaboration (no mocked netlists):
  1. POSITIVE regression: a clean hierarchical design (top instantiating a
     child, with the child's `rst_n` driven straight from a top-level reset)
     no longer reports a false `reset_used_as_data`.
  2. NEGATIVE test: a genuinely broken hierarchical design -- where a reset
     net is ALSO sampled as ordinary data inside the child module -- is still
     reported. A fix that only silenced the check would pass both designs;
     this test requires the checker to tell them apart.

Requires yosys on PATH. Skipped (not failed) when yosys is unavailable, e.g.
on a host without the toolchain -- run this inside the chip-rtl-design
container (or with a bind-mounted yosys) to get a real signal.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import rtl_design_utils as utils  # noqa: E402

_HAS_YOSYS = shutil.which("yosys") is not None

#  NOTE ON SHAPE: matching myTop4_core/DX-42 exactly is essential. The bug
#  only reproduces when the TOP module has its OWN reset-driven flops in its
#  own scope (so `resets` is non-empty for the top-only, unflattened target)
#  *and* separately routes that same reset net into a child instance's
#  `rst_n` port. A top that has no reset-bearing flops of its own returns
#  early from `reset_hygiene.analyze()` before the data-bit scan even runs,
#  which would silently pass regardless of whether the fix works -- exactly
#  the kind of vacuous test this task warns against.
_CLEAN_TOP_V = """
module clean_top (
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] din,
    output reg  [7:0] local_reg,
    output wire [7:0] dout
);
    // top's OWN reset-driven flop, directly in top's scope.
    always @(posedge clk) begin
        if (!rst_n)
            local_reg <= 8'h00;
        else
            local_reg <= din;
    end

    // same rst_n net ALSO routed into a child instance's rst_n port.
    clean_child u_child (
        .clk(clk),
        .rst_n(rst_n),
        .din(din),
        .dout(dout)
    );
endmodule
"""

_CLEAN_CHILD_V = """
module clean_child (
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] din,
    output reg  [7:0] dout
);
    // rst_n is used ONLY inside a synchronous-reset guard: a proper reset,
    // never sampled as data. This mirrors crc16_ccitt.v/bsum16.v from DX-42.
    always @(posedge clk) begin
        if (!rst_n)
            dout <= 8'h00;
        else
            dout <= din;
    end
endmodule
"""

_BROKEN_TOP_V = """
module broken_top (
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] din,
    output reg  [7:0] local_reg,
    output wire [7:0] dout
);
    // top's OWN reset-driven flop, directly in top's scope.
    always @(posedge clk) begin
        if (!rst_n)
            local_reg <= 8'h00;
        else
            local_reg <= din;
    end

    broken_child u_child (
        .clk(clk),
        .rst_n(rst_n),
        .din(din),
        .dout(dout)
    );
endmodule
"""

_BROKEN_CHILD_V = """
module broken_child (
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] din,
    output reg  [7:0] dout
);
    // Genuine defect: rst_n is a real synchronous reset for this flop AND is
    // separately sampled as ordinary data (added into din). Must still be
    // caught as reset_used_as_data after flattening.
    always @(posedge clk) begin
        if (!rst_n)
            dout <= 8'h00;
        else
            dout <= din + {7'b0, rst_n};
    end
endmodule
"""

_CLEAN_EQUIVALENT_SYNC_CLEAR_V = """
module clean_equivalent_sync_clear (
    input  wire clk,
    input  wire rst_n,
    input  wire clear_again,
    input  wire din,
    output reg  dout
);
    always @(posedge clk) begin
        if (!rst_n)
            dout <= 1'b0;
        else if (clear_again)
            dout <= 1'b0;
        else
            dout <= din;
    end
endmodule
"""


@unittest.skipUnless(_HAS_YOSYS, "yosys not on PATH; run inside chip-rtl-design container")
class TestResetHygieneFlatten(unittest.TestCase):
    def _run(self, top, sources):
        tmp = tempfile.mkdtemp(prefix="reset_hygiene_test_")
        out_dir = os.path.join(tmp, "output")
        work_dir = os.path.join(tmp, "workdir")
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(work_dir, exist_ok=True)
        utils.quick_setup(output_dir=out_dir, work_dir=work_dir)

        files = []
        for name, text in sources.items():
            p = os.path.join(tmp, name)
            with open(p, "w") as f:
                f.write(text)
            files.append(p)

        result = utils._reset_hygiene({"top": top}, files, top)
        shutil.rmtree(tmp, ignore_errors=True)
        return result

    def test_clean_hierarchical_reset_is_not_misclassified(self):
        """A reset passed straight into a child's rst_n port must NOT be
        reported as reset_used_as_data once the hierarchy is flattened."""
        result = self._run("clean_top", {
            "clean_top.v": _CLEAN_TOP_V,
            "clean_child.v": _CLEAN_CHILD_V,
        })
        self.assertTrue(result.get("assessable"), result)
        self.assertEqual(result.get("gating_findings"), 0, result.get("findings"))
        kinds = {f["kind"] for f in (result.get("findings") or [])
                 if f["severity"] == "gating"}
        self.assertNotIn("reset_used_as_data", kinds)

    def test_genuine_reset_used_as_data_is_still_caught(self):
        """NEGATIVE TEST (required by DX-146): a real reset-used-as-data
        defect inside a child module must still gate after flattening. A fix
        that merely silenced the check would let this design pass too."""
        result = self._run("broken_top", {
            "broken_top.v": _BROKEN_TOP_V,
            "broken_child.v": _BROKEN_CHILD_V,
        })
        self.assertTrue(result.get("assessable"), result)
        self.assertGreaterEqual(result.get("gating_findings"), 1, result.get("findings"))
        kinds = {f["kind"] for f in (result.get("findings") or [])
                 if f["severity"] == "gating"}
        self.assertIn("reset_used_as_data", kinds)

    def test_equivalent_sync_clear_control_cone_is_not_data(self):
        """Yosys may merge two same-value synchronous clears into one SRST
        control cone. The reset feeding that generated cone is still control,
        not sampled data."""
        result = self._run("clean_equivalent_sync_clear", {
            "clean_equivalent_sync_clear.v": _CLEAN_EQUIVALENT_SYNC_CLEAR_V,
        })
        self.assertTrue(result.get("assessable"), result)
        kinds = {f["kind"] for f in (result.get("findings") or [])
                 if f["severity"] == "gating"}
        self.assertNotIn("reset_used_as_data", kinds, result.get("findings"))


if __name__ == "__main__":
    unittest.main()
