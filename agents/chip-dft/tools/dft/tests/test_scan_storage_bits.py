import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dft_utils import _classify_scan_cells


class ScanStorageBits(unittest.TestCase):
    def test_vector_register_counts_each_scan_bit(self):
        result = _classify_scan_cells({
            "q": {"type": "$dff", "connections": {"Q": [2, 3, 4, 5]}}
        })
        self.assertEqual(result["scannable_ff"], 4)
        self.assertEqual(result["total_sequential"], 4)

    def test_vector_hazards_contribute_bit_population(self):
        result = _classify_scan_cells({
            "q": {"type": "$dff", "connections": {"Q": [2, 3, 4, 5]}},
            "l": {"type": "$dlatch", "connections": {"Q": [6, 7]}},
            "a": {"type": "$adff", "connections": {"Q": [8, 9]}}
        })
        self.assertEqual(result["total_sequential"], 8)
        self.assertEqual(result["hazards"]["latch"], 2)
        self.assertEqual(result["hazards"]["async_set_reset"], 2)
        self.assertEqual(result["coverage_estimate_pct"], 50.0)
        self.assertFalse(result["clean"])

    def test_gate_cell_and_legacy_scalar_remain_one(self):
        result = _classify_scan_cells({
            "q": {"type": "sky130_fd_sc_hd__dfxtp_1"},
            "s": {"type": "$dff"}
        })
        self.assertEqual(result["scannable_ff"], 2)


if __name__ == "__main__":
    unittest.main()
