"""Regression test for DX-150: `reset_hygiene.analyze()` must not report a
false `reset_used_as_data` for a reset that merely passes through an
unflattened blackbox/boundary cell's pin.

BACKGROUND (DX-42 -> DX-150, distinct from DX-146)
---------------------------------------------------
DX-146 fixed the case where `flatten` was never run at all, so only the top
module's own cells were inspected. This is a NARROWER, later gap: `flatten`
DOES run and DOES inline every real RTL submodule, but it cannot inline a
submodule that carries an `inout` port -- e.g. a sky130_ef_io pad cell with a
bidirectional PAD pin. That instance survives as a separate module with ZERO
internal cells: an empty blackbox shell whose pins ARE its entire
"implementation". The old data-bit scan excluded only the literal pin names
{ARST, SRST, CLR, SET, CLK, Q, ALOAD}, with no notion of module boundaries, so
the pad's arbitrary `IN` pin (fed from `PAD`, which carries the external
reset) looked exactly like ordinary data being sampled -- a false
`reset_used_as_data` on a textbook-correct pad-ring connection.

This test proves three things with REAL yosys elaboration (no mocked
netlists), mirroring the sky130_ef_io__gpiov2_pad scenario traced from
myTop4_soc's rtl.9 artifacts:
  1. POSITIVE regression: a reset routed straight through a blackbox pad cell
     (PAD -> IN) into real sequential logic is NOT misclassified as
     reset_used_as_data.
  2. NEGATIVE test (mandatory differential proof): a genuine
     reset-used-as-data defect -- the SAME reset net, routed through the SAME
     kind of blackbox pad cell, but ALSO sampled as ordinary data inside real
     RTL logic -- must STILL be caught. A fix that merely silenced/narrowed
     the check to "ignore this pin" would let this design pass too; this test
     requires the checker to still tell the two designs apart.
  3. `_is_boundary_cell()` unit-level check: a module that still has real
     internal cells (i.e. genuinely NOT flattened, or not a boundary
     primitive) is NOT treated as a boundary, so reset-as-data inside real,
     un-inlined hierarchy is still caught -- this is what stops the fix from
     silently exempting anything that merely happens to still be a submodule
     instance.

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

import reset_hygiene  # noqa: E402
import rtl_design_utils as utils  # noqa: E402

_HAS_YOSYS = shutil.which("yosys") is not None

# A blackbox pad cell shaped like sky130_ef_io__gpiov2_pad: an `inout` PAD
# port (which is why `flatten` cannot inline it) with no body of its own, so
# it survives flatten as a module with zero internal cells.
_PAD_CELL_V = """
(* blackbox *)
module pad_cell(inout wire PAD, output wire IN, input wire OE, input wire OUT);
endmodule
"""

_CLEAN_TOP_V = """
module clean_top (
    inout  wire rst_n_pad,
    input  wire clk,
    input  wire [7:0] din,
    output reg  [7:0] dout
);
    wire rst_n;
    // rst_n_pad (external reset) -> PAD -> IN -> rst_n: correct pad wiring.
    pad_cell u_rst_n_pad (.PAD(rst_n_pad), .IN(rst_n), .OE(1'b0), .OUT(1'b0));

    // rst_n used ONLY as a proper reset, never sampled as data.
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
    inout  wire rst_n_pad,
    input  wire clk,
    input  wire [7:0] din,
    output reg  [7:0] dout
);
    wire rst_n;
    pad_cell u_rst_n_pad (.PAD(rst_n_pad), .IN(rst_n), .OE(1'b0), .OUT(1'b0));

    // Genuine defect: rst_n is a real reset for this flop AND is separately
    // sampled as ordinary data (added into din). Must still be caught, even
    // though the reset also legitimately passes through the same pad cell.
    always @(posedge clk) begin
        if (!rst_n)
            dout <= 8'h00;
        else
            dout <= din + {7'b0, rst_n};
    end
endmodule
"""


@unittest.skipUnless(_HAS_YOSYS, "yosys not on PATH; run inside chip-rtl-design container")
class TestResetHygieneBoundary(unittest.TestCase):
    def _run(self, top, sources):
        tmp = tempfile.mkdtemp(prefix="reset_hygiene_boundary_test_")
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

    def test_reset_through_blackbox_pad_is_not_misclassified(self):
        """A reset routed PAD -> IN through an unflattened blackbox pad cell
        must NOT be reported as reset_used_as_data (DX-150)."""
        result = self._run("clean_top", {
            "pad_cell.v": _PAD_CELL_V,
            "clean_top.v": _CLEAN_TOP_V,
        })
        self.assertTrue(result.get("assessable"), result)
        self.assertEqual(result.get("gating_findings"), 0, result.get("findings"))
        kinds = {f["kind"] for f in (result.get("findings") or [])
                 if f["severity"] == "gating"}
        self.assertNotIn("reset_used_as_data", kinds)

    def test_genuine_defect_through_same_pad_is_still_caught(self):
        """MANDATORY DIFFERENTIAL PROOF: a real reset-used-as-data defect,
        routed through the identical blackbox pad cell, must still gate. A
        fix that merely silenced the check on pad boundaries would let this
        design pass too."""
        result = self._run("broken_top", {
            "pad_cell.v": _PAD_CELL_V,
            "broken_top.v": _BROKEN_TOP_V,
        })
        self.assertTrue(result.get("assessable"), result)
        self.assertGreaterEqual(result.get("gating_findings"), 1, result.get("findings"))
        kinds = {f["kind"] for f in (result.get("findings") or [])
                 if f["severity"] == "gating"}
        self.assertIn("reset_used_as_data", kinds)

    def test_is_boundary_cell_requires_zero_cells_or_blackbox_attr(self):
        """Unit-level guard: a module that still has real internal cells is
        NOT a boundary, regardless of name -- only an empty shell (or an
        explicit blackbox/whitebox attribute) qualifies. This is what stops
        the fix from becoming a name-based exemption in disguise."""
        mods = {
            "empty_shell": {"cells": {}},
            "real_logic": {"cells": {"c1": {"type": "$and"}}},
            "explicit_blackbox": {"attributes": {"blackbox": 1}, "cells": {}},
        }
        self.assertTrue(reset_hygiene._is_boundary_cell("empty_shell", mods))
        self.assertFalse(reset_hygiene._is_boundary_cell("real_logic", mods))
        self.assertTrue(reset_hygiene._is_boundary_cell("explicit_blackbox", mods))
        # Yosys native cell types ($adff, $and, ...) are never module names.
        self.assertFalse(reset_hygiene._is_boundary_cell("$adff", mods))
        self.assertFalse(reset_hygiene._is_boundary_cell("unknown_module", mods))


if __name__ == "__main__":
    unittest.main()
