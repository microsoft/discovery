"""`scan_analysis` output keys must bind the shared progress registry's families.

Guards tickets/dft/mytop4-hiersoc-global-dft-field-name-mismatch.md: the tool
emitted `results.flip_flops` / `results.scannable_ff` /
`signoff_evidence.scan_hazards`, none of which the `dft` obligation-family
recipe recognizes, so an honest 32/32-scannable zero-hazard pass evaluated
`scannability` and `hazards` as `not_assessable`, forced `gate_closed: false`,
and was rejected as `gate_not_closed` until the caller hand-aliased the same
numbers under the registry's own names.
"""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

import cde_progress  # the copy vendored beside the tool -- the one in the image


def _envelope(total=32, scannable=32, hazards=None, legacy_only=False):
    hazards = hazards or {"latch": 0, "async_set_reset": 0, "gated_or_other": 0}
    results = {
        "flip_flops": {"value": total, "unit": "count"},
        "scannable_ff": {"value": scannable, "unit": "count"},
        "scan_coverage_estimate": {"value": 100.0, "unit": "percent"},
    }
    signoff = {"scan_hazards": hazards}
    validation = {"verdict": "pass"}
    if not legacy_only:
        results.update({
            "total_sequential": {"value": total, "unit": "count"},
            "eligible_scan_flops": {"value": scannable, "unit": "count"},
            "latches": {"value": hazards["latch"], "unit": "count"},
            "async_set_reset_hazards": {
                "value": hazards["async_set_reset"], "unit": "count"},
            "other_hazards": {"value": hazards["gated_or_other"], "unit": "count"},
        })
        signoff["hazards"] = hazards
        validation["all_hazards_zero"] = not any(hazards.values())
    return {
        "tool": "dft", "stage": "dft", "status": "completed", "verdict": "pass",
        "results": results, "qor_metrics": {}, "signoff_evidence": signoff,
        "validation": validation,
    }


class TestScanAnalysisBindsItsFamilies(unittest.TestCase):
    def _progress(self, **kw):
        return cde_progress.compute_progress(_envelope(**kw), "dft")

    def test_scannability_and_hazards_bind(self):
        families = self._progress()["families"]
        for name in ("scannability", "hazards"):
            self.assertIn(name, families)
            self.assertFalse(families[name].get("not_assessable"), name)
            self.assertEqual(families[name]["residual"], 0.0, name)

    def test_legacy_only_keys_leave_both_families_unassessed(self):
        # Non-vacuity: the pre-fix envelope shape must still fail to bind.
        unassessed = self._progress(legacy_only=True)["not_assessable_families"]
        self.assertIn("scannability", unassessed)
        self.assertIn("hazards", unassessed)

    def test_unscannable_flops_open_the_scannability_residual(self):
        families = self._progress(total=32, scannable=30)["families"]
        self.assertEqual(families["scannability"]["residual"], 2.0)

    def test_any_hazard_category_opens_the_hazards_residual(self):
        for category in ("latch", "async_set_reset", "gated_or_other"):
            hazards = {"latch": 0, "async_set_reset": 0, "gated_or_other": 0}
            hazards[category] = 3
            families = self._progress(hazards=hazards)["families"]
            self.assertGreater(families["hazards"]["residual"], 0.0, category)

    def test_analysis_only_families_stay_honestly_unassessed(self):
        # scan_analysis does not insert, stitch or simulate; those obligations
        # must remain not_assessable rather than be counted as satisfied.
        unassessed = set(self._progress()["not_assessable_families"])
        self.assertTrue(
            {"insertion", "chain_integrity", "shift_simulation"} <= unassessed)

    def test_registry_paths_this_tool_now_emits_are_the_declared_ones(self):
        recipe = cde_progress.STAGE_RESIDUALS["dft"]["obligation_families"]
        declared = {
            path
            for family in ("scannability", "hazards")
            for entry in recipe[family]
            for key in ("paths", "population_paths", "achieved_paths")
            for path in entry.get(key, [])
        }
        emitted = {
            "results.total_sequential", "results.eligible_scan_flops",
            "results.latches", "results.async_set_reset_hazards",
            "results.other_hazards", "validation.all_hazards_zero",
        }
        self.assertTrue(emitted <= declared,
                        "emitted but undeclared: %s" % sorted(emitted - declared))


if __name__ == "__main__":
    unittest.main()
