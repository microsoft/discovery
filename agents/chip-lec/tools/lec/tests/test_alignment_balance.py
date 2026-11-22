"""Differential tests for DX-154's `alignment` arithmetic-consistency check.

`alignment` previously self-reported "ok" on an internally incoherent LEC
triple (equivalent_points=15, total_partitions=19, unproven_points=0 -- 19-15=4,
not 0) because the residual invariant only ever compared `unproven_points`
(correctly 0, from the verdict-bearing flat proof) against `gate_closed`. It
never checked that `total_partitions` and `equivalent_points` came from the
SAME run. This exercises `compute_progress` against the vendored
`cde_progress.py` that is actually baked into the chip-lec image.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cde_progress


def _lec_envelope(equivalent_points, total_partitions, unproven_points,
                   verdict="pass"):
    return {
        "stage": "lec",
        "status": "completed",
        "results": {
            "unproven_points": {"value": unproven_points, "class": "gating"},
            "equivalent_points": {"value": equivalent_points},
            "total_partitions": {"value": total_partitions},
        },
        "validation": {"verdict": verdict},
    }


class TestLecAlignmentBalanceCheck(unittest.TestCase):
    def test_balanced_single_engine_pass_is_ok(self):
        env = _lec_envelope(19, 19, 0, verdict="pass")
        prog = cde_progress.compute_progress(env, stage="lec")
        self.assertEqual(prog["alignment"], "ok")
        self.assertTrue(prog["gate_closed"])
        self.assertEqual(prog["balance_check"],
                          {"total_partitions": 19.0, "equivalent_points": 19.0,
                           "unproven_points": 0.0, "balanced": True})

    def test_mixed_basis_triple_is_flagged_metric_defect(self):
        # The exact DX-154 symptom: 15 equivalent / 19 total (partitioned eqy)
        # paired with 0 unproven (from a separate superseding flat proof).
        env = _lec_envelope(15, 19, 0, verdict="pass")
        prog = cde_progress.compute_progress(env, stage="lec")
        self.assertEqual(prog["alignment"], "metric_defect")
        self.assertEqual(prog["alignment_severity"], "blocking")
        self.assertFalse(prog["balance_check"]["balanced"])
        self.assertIn("arithmetic balance check failed",
                      prog["alignment_detail"])

    def test_fixed_flat_basis_triple_is_balanced_and_ok(self):
        # After the DX-154 fix, the same run reports the flat-proof basis for
        # all three numbers together: 49 compared / 49 proven / 0 unproven.
        env = _lec_envelope(49, 49, 0, verdict="pass")
        prog = cde_progress.compute_progress(env, stage="lec")
        self.assertEqual(prog["alignment"], "ok")
        self.assertTrue(prog["balance_check"]["balanced"])

    def test_must_still_fail_genuine_nonequivalence_stays_fail(self):
        # A real counterexample with no superseding proof: verdict fail,
        # gate_closed false, and the (balanced, failing) triple must not be
        # relabelled as a metric defect just because it disagrees with a pass.
        env = _lec_envelope(15, 19, 4, verdict="fail")
        prog = cde_progress.compute_progress(env, stage="lec")
        self.assertFalse(prog["gate_closed"])
        self.assertEqual(prog["verdict_normalized"], "fail")
        self.assertTrue(prog["balance_check"]["balanced"])
        self.assertEqual(prog["alignment"], "ok")


if __name__ == "__main__":
    unittest.main()
