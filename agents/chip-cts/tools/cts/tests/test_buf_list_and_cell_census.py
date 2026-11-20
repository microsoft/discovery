"""Buf-list bracing, buffer counting, and the inserted-cell census.

Guards the two CTS tool tickets:
  * .../cts/mytop4-hiersoc-crc16_ccitt-cts-buf-list-tcl-brace-and-diagnostic-count-defects.md
    -- a JSON list (the PDK binding's native shape) was joined into a bare
    space-separated string and spliced into `-buf_list` unbraced, so OpenSTA
    read the names after the first as stray positional args and failed the run
    closed with STA-0564; and the buffer-count diagnostic substring-matched that
    same joined string against the DEF, so it read 0 on every multi-size list.
  * .../cts/mytop4-hiersoc-bsum16-cts-tritoncts-dummy-load-master-bypasses-buf-list.md
    -- TritonCTS dummy-load balancing draws its load cell from the whole
    library, not from `-buf_list`, so an unapproved master can ride along with a
    clean skew and zero unbuffered clocks.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cts_utils


class TestBufferNameList(unittest.TestCase):
    NAMES = ["sky130_fd_sc_hd__clkbuf_1", "sky130_fd_sc_hd__clkbuf_16"]

    def test_json_array_is_the_binding_native_shape(self):
        self.assertEqual(cts_utils._buffer_name_list(self.NAMES), self.NAMES)

    def test_pre_braced_workaround_string_is_not_double_braced(self):
        braced = "{" + " ".join(self.NAMES) + "}"
        self.assertEqual(cts_utils._buffer_name_list(braced), self.NAMES)

    def test_bare_space_separated_string(self):
        self.assertEqual(
            cts_utils._buffer_name_list(" ".join(self.NAMES)), self.NAMES)

    def test_single_name(self):
        self.assertEqual(cts_utils._buffer_name_list("one"), ["one"])

    def test_absent_is_empty_not_a_crash(self):
        self.assertEqual(cts_utils._buffer_name_list(None), [])
        self.assertEqual(cts_utils._buffer_name_list(""), [])

    def test_round_trip_produces_exactly_one_brace_level(self):
        for supplied in (self.NAMES, " ".join(self.NAMES),
                         "{" + " ".join(self.NAMES) + "}"):
            names = cts_utils._buffer_name_list(supplied)
            tcl = "{" + " ".join(names) + "}"
            self.assertEqual(tcl, "{" + " ".join(self.NAMES) + "}")
            self.assertNotIn("{{", tcl)


class TestMasterCounting(unittest.TestCase):
    """The old diagnostic matched the joined parameter string; a DEF never has it."""

    DEF = """COMPONENTS 4 ;
- clkbuf_0_clk sky130_fd_sc_hd__clkbuf_16 + PLACED ( 100 200 ) N ;
- clkbuf_2_0__f_clk sky130_fd_sc_hd__clkbuf_16 + PLACED ( 300 200 ) N ;
- clkload0 sky130_fd_sc_hd__clkbuf_1 + PLACED ( 500 200 ) N ;
- _0_ sky130_fd_sc_hd__nand2_1 + PLACED ( 700 200 ) N ;
END COMPONENTS
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "cts.def")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(self.DEF)

    def test_counts_every_matching_master(self):
        self.assertEqual(cts_utils._count_masters_in_def(
            self.path, ["sky130_fd_sc_hd__clkbuf_16",
                        "sky130_fd_sc_hd__clkbuf_1"]), 3)

    def test_a_master_absent_from_the_def_contributes_zero(self):
        self.assertEqual(cts_utils._count_masters_in_def(
            self.path, ["sky130_fd_sc_hd__clkbuf_8"]), 0)

    def test_prefix_of_a_longer_master_name_does_not_match(self):
        # `clkbuf_1` must not count the three `clkbuf_16` instances.
        self.assertEqual(cts_utils._count_masters_in_def(
            self.path, ["sky130_fd_sc_hd__clkbuf_1"]), 1)

    def test_non_buffer_masters_are_not_counted(self):
        self.assertEqual(cts_utils._count_masters_in_def(
            self.path, ["sky130_fd_sc_hd__clkbuf_16"]), 2)

    def test_missing_file_is_none_not_zero(self):
        self.assertIsNone(cts_utils._count_masters_in_def(
            os.path.join(self.tmp.name, "absent.def"), ["x"]))

    def test_no_masters_is_none_not_zero(self):
        self.assertIsNone(cts_utils._count_masters_in_def(self.path, []))


class TestInsertedCellCensus(unittest.TestCase):
    LOG = (
        "[INFO CTS-0018] Created 5 clock buffers.\n"
        "__CTS_NEW__ clkbuf_0_clk sky130_fd_sc_hd__clkbuf_16\n"
        "__CTS_NEW__ clkload0 sky130_fd_sc_hd__clkinv_2\n"
        "__CTS_NEW__ clkload1 sky130_fd_sc_hd__clkbuf_8\n"
        "[INFO ODB-0227] LEF file: ...\n"
    )

    def test_every_new_instance_is_captured_with_its_master(self):
        self.assertEqual(
            cts_utils._parse_inserted_cells(self.LOG),
            [("clkbuf_0_clk", "sky130_fd_sc_hd__clkbuf_16"),
             ("clkload0", "sky130_fd_sc_hd__clkinv_2"),
             ("clkload1", "sky130_fd_sc_hd__clkbuf_8")])

    def test_unapproved_dummy_load_is_identified(self):
        approved = {"sky130_fd_sc_hd__clkbuf_8", "sky130_fd_sc_hd__clkbuf_16"}
        inserted = cts_utils._parse_inserted_cells(self.LOG)
        unapproved = sorted({m for _n, m in inserted if m not in approved})
        self.assertEqual(unapproved, ["sky130_fd_sc_hd__clkinv_2"])
        self.assertEqual(
            sum(1 for _n, m in inserted if m not in approved), 1)

    def test_all_approved_yields_no_finding(self):
        approved = {"sky130_fd_sc_hd__clkbuf_8", "sky130_fd_sc_hd__clkbuf_16",
                    "sky130_fd_sc_hd__clkinv_2"}
        inserted = cts_utils._parse_inserted_cells(self.LOG)
        self.assertEqual([m for _n, m in inserted if m not in approved], [])

    def test_absent_census_is_empty_so_the_gate_reports_not_measured(self):
        # No census lines must read as "not measured", never as "nothing
        # unapproved was inserted".
        self.assertEqual(cts_utils._parse_inserted_cells("no markers here"), [])
        self.assertEqual(cts_utils._parse_inserted_cells(""), [])
        self.assertEqual(cts_utils._parse_inserted_cells(None), [])


if __name__ == "__main__":
    unittest.main()
