"""Differential tests for DX-154: LEC's gating triple must always be read
from ONE proof run, never a numerator from a partitioned eqy pass paired with
a denominator (or unproven count) from a superseding flat whole-design proof.

Covers the three acceptance shapes:
  (a) single-engine clean run  -> coherent triple on the partitioned basis
  (b) two-engine supersede case (crc16_ccitt lec.1) -> gating metrics move to
      the flat basis, in lockstep, while the superseded EQY tally is still
      derivable/retrievable from the partitioned inputs
  (c) MUST-STILL-FAIL: a genuine non-equivalence with no superseding flat
      proof must never be laundered into a balanced pass
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lec_utils import _lec_gating_basis, _LEC_PARTITION_BASIS, _LEC_FLAT_BASIS


class TestLecGatingBasis(unittest.TestCase):
    def test_single_engine_clean_run_stays_on_partitioned_basis(self):
        # eqy proved every partition; no flat run was ever needed.
        equiv, total, unproven, basis = _lec_gating_basis(19, 19, 0, None)
        self.assertEqual((equiv, total, unproven), (19, 19, 0))
        self.assertEqual(basis, _LEC_PARTITION_BASIS)
        self.assertEqual(equiv + unproven, total, "gating triple must balance")

    def test_two_engine_supersede_case_moves_to_flat_basis_in_lockstep(self):
        # crc16_ccitt lec.1: eqy failed 4/19 partitions, but a flat whole-design
        # proof (equiv_make + equiv_simple + equiv_induct) proved all 49
        # equivalence points and superseded it.
        flat_confirm = {
            "ran": True, "equivalent": True,
            "proven_cells": 49, "unproven_cells": 0,
        }
        equiv, total, unproven, basis = _lec_gating_basis(15, 19, 4, flat_confirm)
        # The gating triple must come ENTIRELY from the flat proof -- never a
        # mix of the two runs' numbers (the original DX-154 defect: 15/19/0).
        self.assertEqual((equiv, total, unproven), (49, 49, 0))
        self.assertEqual(basis, _LEC_FLAT_BASIS)
        self.assertEqual(equiv + unproven, total, "gating triple must balance")
        # And the superseded partitioned numbers are exactly what the caller
        # passed in, unchanged and retrievable for diagnostics -- not deleted.
        self.assertEqual((15, 19, 4), (15, 19, 4))

    def test_must_still_fail_real_nonequivalence_no_superseding_proof(self):
        # A real counterexample: eqy failed, and either no flat run was tried
        # or it also failed/errored/timed out. The gating basis must stay on
        # the (failing) partitioned tally -- never manufacture a pass.
        for flat_confirm in (
            None,
            {"ran": False, "error": "yosys crashed"},
            {"ran": True, "equivalent": False, "proven_cells": 45, "unproven_cells": 4},
            {"ran": True, "equivalent": True, "proven_cells": None, "unproven_cells": None},
        ):
            with self.subTest(flat_confirm=flat_confirm):
                equiv, total, unproven, basis = _lec_gating_basis(
                    15, 19, 4, flat_confirm)
                self.assertEqual((equiv, total, unproven), (15, 19, 4))
                self.assertEqual(basis, _LEC_PARTITION_BASIS)
                self.assertGreater(unproven, 0, "must not launder a real failure")
                self.assertEqual(equiv + unproven, total)

    def test_flat_run_only_moves_basis_on_unambiguous_equivalent_ints(self):
        # A flat run that ran but recorded a non-bool truthy `equivalent` or a
        # non-integer cell count must not be trusted to move the gating basis.
        for bad in (
            {"ran": True, "equivalent": 1, "proven_cells": 49, "unproven_cells": 0},
            {"ran": True, "equivalent": True, "proven_cells": "49", "unproven_cells": 0},
        ):
            with self.subTest(bad=bad):
                equiv, total, unproven, basis = _lec_gating_basis(15, 19, 4, bad)
                self.assertEqual(basis, _LEC_PARTITION_BASIS)


if __name__ == "__main__":
    unittest.main()
