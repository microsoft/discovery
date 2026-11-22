"""Differential tests for DX-162's key-point-count plausibility gate.

Origin defect: `lec-post-synth.5` reported `equivalent_points=2` (of
`total_partitions=4`) for bsum16 -- a design whose real RTL has 33 flops --
and set `whole_design_confirmation.equivalent=true`. A 2-key-point partition
cannot constitute a whole-design proof of a 33-flop design; the count was
never sanity-checked against either side's own measured sequential-element
population.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lec_utils import _key_point_plausibility


class TestKeyPointPlausibility(unittest.TestCase):
    def test_historical_escape_shape_is_implausible(self):
        # The exact DX-162 escape numbers: 2 equivalent points on a design
        # whose real RTL/netlist both have 33 sequential elements.
        result = _key_point_plausibility(2, 33, 33)
        self.assertFalse(result["plausible"])
        self.assertTrue(result["checked"])
        self.assertEqual(result["floor"], 33)
        self.assertIn("cannot cover every flop", result["reason"])

    def test_population_at_or_above_floor_is_plausible(self):
        result = _key_point_plausibility(33, 33, 33)
        self.assertTrue(result["plausible"])
        result = _key_point_plausibility(49, 33, 33)
        self.assertTrue(result["plausible"])

    def test_floor_is_the_larger_of_the_two_sides(self):
        # 32-flop reference vs 33-flop revised (the DX-161 bsum16 shape):
        # a population of 32 is still implausible because it doesn't cover
        # the LARGER (revised) side's 33 flops.
        result = _key_point_plausibility(32, 32, 33)
        self.assertFalse(result["plausible"])
        self.assertEqual(result["floor"], 33)

    def test_unmeasurable_sequential_counts_are_not_assessed_not_blocked(self):
        result = _key_point_plausibility(2, None, 33)
        self.assertFalse(result["checked"])
        self.assertTrue(result["plausible"])  # never silently blocks on missing data
        result = _key_point_plausibility(None, 33, 33)
        self.assertFalse(result["checked"])
        self.assertTrue(result["plausible"])

    def test_zero_sequential_elements_on_both_sides_is_not_meaningful(self):
        # A purely combinational design (no flops on either side) has no
        # plausibility floor to violate.
        result = _key_point_plausibility(1, 0, 0)
        self.assertFalse(result["checked"])
        self.assertTrue(result["plausible"])


if __name__ == "__main__":
    unittest.main()
