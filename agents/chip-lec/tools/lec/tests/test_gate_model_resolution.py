"""Gate-side cell-model resolution: dict-shaped Liberty, shared models, fallback.

Covers the three defects recorded in
tickets/lec-post-synth/mytop4-hiersoc-crc16_ccitt-lec-post-synth-udp-model-and-
shared-model-wiring.md, all of which failed SILENTLY -- the run continued with an
empty or wrong gate-side model and surfaced later as an unrelated
"module not part of the design" error.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lec_utils


class TestDictShapedLibertyBinding(unittest.TestCase):
    """`pdk_binding.liberty` is a {"path","sha256"} RECORD, not a bare string."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lib = os.path.join(self.tmp.name, "cells.lib")
        with open(self.lib, "w", encoding="utf-8") as handle:
            handle.write("library (cells) { }\n")
        self.sha256 = lec_utils._hash_input_file(self.lib)["sha256"]

    def test_binding_dict_resolves_to_a_real_path(self):
        path, expected, error = lec_utils._resolve_liberty(
            {"pdk_binding": {"liberty": {"path": self.lib,
                                         "sha256": self.sha256}}})
        self.assertIsNone(error)
        self.assertEqual(path, self.lib)
        self.assertEqual(expected, self.sha256)

    def test_stringified_dict_is_never_a_path(self):
        # The exact defect: `os.path.exists(str({"path": ...}))` is always False,
        # so the Liberty branch silently no-opped.
        self.assertFalse(
            os.path.exists(str({"path": self.lib, "sha256": self.sha256})))

    def test_declared_detects_every_binding_shape(self):
        self.assertTrue(lec_utils._liberty_declared({"liberty": self.lib}))
        self.assertTrue(lec_utils._liberty_declared(
            {"pdk_binding": {"liberty": {"path": self.lib}}}))
        self.assertTrue(lec_utils._liberty_declared(
            {"pdk_binding": {"references": {"liberty_tt_025C_1v80": self.lib}}}))
        self.assertFalse(lec_utils._liberty_declared({}))
        self.assertFalse(lec_utils._liberty_declared({"pdk_binding": {}}))

    def test_declared_but_wrong_hash_is_an_error_not_a_skip(self):
        _, _, error = lec_utils._resolve_liberty(
            {"pdk_binding": {"liberty": {"path": self.lib, "sha256": "00" * 32}}})
        self.assertIn("SHA-256", error)

    def test_read_block_is_functional_and_quoted(self):
        block = lec_utils._liberty_read_block(self.lib)
        self.assertIn("read_liberty -ignore_miss_func", block)
        self.assertNotIn("-lib", block)
        # Yosys script arguments must escape Windows backslashes as well.
        expected = '"' + self.lib.replace("\\", "\\\\").replace('"', '\\"') + '"'
        self.assertIn(expected, block)


class TestSharedModelsReachTheGateBlock(unittest.TestCase):
    """`shared_functional_models` was wired into every path except the proof."""

    def _text(self, shared_model_read):
        return lec_utils._eqy_problem_text(
            top="dut", read_ref="read_verilog gold.v\n",
            lib_read="read_liberty -ignore_miss_func cells.lib\n",
            shared_model_read=shared_model_read,
            read_rev="read_verilog gate.v\n",
            init_norm="opt -fast\n", gate_model_guard="flatten\n",
            match_block="", depth=10)

    def test_shared_model_read_appears_in_the_gate_section(self):
        text = self._text("read_verilog -sv \"primitives.v\"\n")
        gate = text.split("[gate]", 1)[1].split("[strategy", 1)[0]
        self.assertIn("primitives.v", gate)

    def test_shared_model_read_precedes_the_revised_netlist(self):
        text = self._text("read_verilog -sv \"primitives.v\"\n")
        gate = text.split("[gate]", 1)[1]
        self.assertLess(gate.index("primitives.v"), gate.index("gate.v"))

    def test_absent_shared_models_leave_the_gate_block_unchanged(self):
        self.assertNotIn("primitives.v", self._text(""))

    def test_gold_section_never_reads_gate_side_models(self):
        text = self._text("read_verilog -sv \"primitives.v\"\n")
        gold = text.split("[gold]", 1)[1].split("[gate]", 1)[0]
        self.assertNotIn("primitives.v", gold)
        self.assertNotIn("cells.lib", gold)


class TestPartitionBoundaryEvidence(unittest.TestCase):
    """A partition counterexample is unreadable without its cut structure."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._work, self._out = lec_utils._WORK_DIR, lec_utils._OUTPUT_DIR
        lec_utils._WORK_DIR = os.path.join(self.tmp.name, "work")
        lec_utils._OUTPUT_DIR = os.path.join(self.tmp.name, "out")
        os.makedirs(os.path.join(lec_utils._WORK_DIR, "lec", "partitions"))
        os.makedirs(lec_utils._OUTPUT_DIR)

    def tearDown(self):
        lec_utils._WORK_DIR, lec_utils._OUTPUT_DIR = self._work, self._out

    def _write(self, name, inbits, outbits=None):
        path = os.path.join(lec_utils._WORK_DIR, "lec", "partitions",
                            name + ".json")
        with open(path, "w", encoding="utf-8") as handle:
            # MEASURED eqy shape: the spec is nested under "partition" and
            # in/outbits are DICTS keyed by signal name.
            json.dump({"partition": {"name": name, "inbits": inbits,
                                     "outbits": outbits or {}}}, handle)

    def test_free_boundary_inputs_are_recorded_per_failing_partition(self):
        self._write("dut.crc_nxt.5",
                    {"crc[0]": [0], "data[0]": [0], "crc_nxt[0]": [0]},
                    {"crc_nxt[5]": [0]})
        self._write("dut.crc_nxt.0", {"crc[0]": [0]}, {"crc_nxt[0]": [0]})
        with open(os.path.join(lec_utils._WORK_DIR, "lec", "partition.log"),
                  "w", encoding="utf-8") as handle:
            handle.write("Add gate.dut/insbuf: \\sum [0] -> \\sum_reg [0]\n")
        evidence = lec_utils._partition_boundary_evidence({"dut.crc_nxt.5"})
        self.assertEqual(evidence["partition_log"], "partition.log")
        self.assertIn("crc_nxt[0]",
                      evidence["free_boundary_inputs"]["dut.crc_nxt.5"])
        self.assertTrue(os.path.isfile(
            os.path.join(lec_utils._OUTPUT_DIR, "partition.log")))

    def test_a_sibling_output_freed_as_an_input_is_identified(self):
        # THE discriminator both hand analyses used: the failing partition's
        # free input is another partition's OUTPUT, not a primary input.
        self._write("dut.crc_nxt.5",
                    {"crc[0]": [0], "crc_nxt[0]": [0]}, {"crc_nxt[5]": [0]})
        self._write("dut.crc_nxt.0", {"crc[0]": [0]}, {"crc_nxt[0]": [0]})
        evidence = lec_utils._partition_boundary_evidence({"dut.crc_nxt.5"})
        shared = evidence["free_inputs_that_are_partition_outputs"]
        self.assertEqual(shared["dut.crc_nxt.5"], {"crc_nxt[0]": "dut.crc_nxt.0"})

    def test_a_genuine_primary_input_is_not_flagged_as_shared(self):
        self._write("dut.crc_nxt.0", {"crc[0]": [0]}, {"crc_nxt[0]": [0]})
        evidence = lec_utils._partition_boundary_evidence({"dut.crc_nxt.0"})
        self.assertEqual(evidence["free_inputs_that_are_partition_outputs"], {})
        self.assertEqual(evidence["free_boundary_inputs"]["dut.crc_nxt.0"],
                         ["crc[0]"])

    def test_proved_partitions_are_not_collected(self):
        self._write("dut.crc_nxt.0", {"crc[0]": [0]})
        evidence = lec_utils._partition_boundary_evidence(set())
        self.assertEqual(evidence["free_boundary_inputs"], {})

    def test_missing_workdir_is_reported_not_raised(self):
        lec_utils._WORK_DIR = os.path.join(self.tmp.name, "absent")
        evidence = lec_utils._partition_boundary_evidence({"dut.sum.0"})
        self.assertIsNone(evidence["partition_log"])
        self.assertEqual(evidence["free_boundary_inputs"], {})


if __name__ == "__main__":
    unittest.main()
