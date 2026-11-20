"""Tests for exact shared-blackbox semantics in the flat LEC harness."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lec_utils


class TestSharedBlackboxMiter(unittest.TestCase):
    def setUp(self):
        self.prepared = {
            "modules": {
                "gold": {"cells": {
                    "u_pad": {"type": "io_pad"},
                }},
                "gate": {"cells": {
                    "u_pad": {"type": "io_pad"},
                }},
            }
        }
        self.interfaces = {
            "modules": {
                "io_pad": {"ports": {
                    "A": {"direction": "input", "bits": [2]},
                    "Y": {"direction": "output", "bits": [3]},
                }}
            }
        }
        self.miter = {
            "modules": {
                "equiv": {
                    "ports": {},
                    "cells": {
                        "u_pad_gold": {
                            "type": "io_pad",
                            "connections": {"A": [10], "Y": [20]},
                        },
                        "u_pad_gate": {
                            "type": "io_pad",
                            "connections": {"A": [10], "Y": [30]},
                        },
                        "consumer": {
                            "type": "$not",
                            "connections": {"A": [30], "Y": [40]},
                        },
                    },
                    "netnames": {
                        "gold_y": {"bits": [20]},
                        "gate_y": {"bits": [30]},
                    },
                }
            }
        }

    def test_exact_pair_shares_output_and_removes_duplicate(self):
        report = lec_utils._share_blackbox_outputs_in_miter(
            self.prepared, self.miter, self.interfaces, "equiv", ["io_pad"])
        cells = self.miter["modules"]["equiv"]["cells"]
        self.assertNotIn("u_pad_gold", cells)
        self.assertNotIn("u_pad_gate", cells)
        self.assertEqual(cells["consumer"]["connections"]["A"], [20])
        self.assertEqual(report["shared_pair_count"], 1)
        self.assertEqual(report["shared_output_bits"], 1)
        self.assertFalse(report["positional_mapping"])

    def test_input_width_mismatch_is_rejected(self):
        bad = copy.deepcopy(self.miter)
        bad["modules"]["equiv"]["cells"]["u_pad_gate"]["connections"]["A"] = [11, 12]
        with self.assertRaisesRegex(ValueError, "input width mismatch"):
            lec_utils._share_blackbox_outputs_in_miter(
                self.prepared, bad, self.interfaces, "equiv", ["io_pad"])

    def test_same_width_input_rewire_is_rejected(self):
        bad = copy.deepcopy(self.miter)
        bad["modules"]["equiv"]["cells"]["u_pad_gate"]["connections"]["A"] = [11]
        with self.assertRaisesRegex(ValueError, "input source mismatch"):
            lec_utils._share_blackbox_outputs_in_miter(
                self.prepared, bad, self.interfaces, "equiv", ["io_pad"])

    def test_unintended_residual_cell_is_rejected(self):
        bad = copy.deepcopy(self.prepared)
        bad["modules"]["gate"]["cells"]["u_hidden"] = {"type": "mystery_cell"}
        with self.assertRaisesRegex(ValueError, "unmodelled non-internal"):
            lec_utils._share_blackbox_outputs_in_miter(
                bad, self.miter, self.interfaces, "equiv", ["io_pad"])

    def test_instance_set_mismatch_is_rejected(self):
        bad = copy.deepcopy(self.prepared)
        del bad["modules"]["gate"]["cells"]["u_pad"]
        with self.assertRaisesRegex(ValueError, "instance set differs"):
            lec_utils._share_blackbox_outputs_in_miter(
                bad, self.miter, self.interfaces, "equiv", ["io_pad"])


if __name__ == "__main__":
    unittest.main()
