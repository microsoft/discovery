"""RC-model clamp disclosure must be DERIVED, never defaulted.

Guards tickets/extraction/mytop4-hiersoc-crc16_ccitt-extraction-cde-claims-per-
corner-rc-resolution-through-null-binding-field.md: `corner_cnt_clamped_to_rc_
model` was the literal `False` and `rc_model_corners` the literal `None`, so an
envelope reporting three per-corner SPEFs denied the very clamp that made all
three byte-identical.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import extraction_utils


class TestSpefContentDigest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _spef(self, name, date, body="*D_NET n1 1.0\n"):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("*SPEF \"IEEE 1481-1998\"\n")
            handle.write('*DATE "%s"\n' % date)
            handle.write(body)
        return path

    def test_timestamp_only_difference_hashes_equal(self):
        a = self._spef("a.spef", "01:23:48 Tuesday September 29, 2026")
        b = self._spef("b.spef", "01:23:49 Tuesday September 29, 2026")
        self.assertEqual(extraction_utils._spef_content_digest(a),
                         extraction_utils._spef_content_digest(b))

    def test_real_rc_difference_hashes_differently(self):
        a = self._spef("a.spef", "t", body="*D_NET n1 1.0\n")
        b = self._spef("b.spef", "t", body="*D_NET n1 2.0\n")
        self.assertNotEqual(extraction_utils._spef_content_digest(a),
                            extraction_utils._spef_content_digest(b))

    def test_missing_file_is_none_not_a_crash(self):
        self.assertIsNone(extraction_utils._spef_content_digest(
            os.path.join(self.tmp.name, "absent.spef")))


class TestClampDerivation(unittest.TestCase):
    """The clamp is `distinct RC models < corners`, computed from the plan."""

    @staticmethod
    def _clamp(plan):
        models = {}
        for item in plan:
            key = (item.get("verification") or {}).get("sha256") or item["rc_rules"]
            models.setdefault(key, []).append(item["corner"])
        return len(models), len(models) < len(plan), {
            digest: sorted(names)
            for digest, names in models.items() if len(names) > 1}

    def test_three_corners_one_model_is_a_total_clamp(self):
        plan = [{"corner": c, "rc_rules": "/r.spef_extractor",
                 "verification": {"sha256": "aa"}}
                for c in ("tt_025C_1v80", "ss_100C_1v60", "ff_n40C_1v95")]
        count, clamped, shared = self._clamp(plan)
        self.assertEqual(count, 1)
        self.assertTrue(clamped)
        self.assertEqual(shared["aa"],
                         ["ff_n40C_1v95", "ss_100C_1v60", "tt_025C_1v80"])

    def test_distinct_models_per_corner_are_not_clamped(self):
        plan = [{"corner": "tt", "rc_rules": "/tt", "verification": {"sha256": "a"}},
                {"corner": "ss", "rc_rules": "/ss", "verification": {"sha256": "b"}}]
        count, clamped, shared = self._clamp(plan)
        self.assertEqual(count, 2)
        self.assertFalse(clamped)
        self.assertEqual(shared, {})

    def test_single_corner_run_is_never_clamped(self):
        plan = [{"corner": "tt", "rc_rules": "/tt", "verification": {"sha256": "a"}}]
        count, clamped, _ = self._clamp(plan)
        self.assertEqual(count, 1)
        self.assertFalse(clamped)


class TestResolutionClaimMatchesMode(unittest.TestCase):
    """A CDE must not name a binding key it never read."""

    def test_source_text_no_longer_hard_codes_the_clamp_literals(self):
        src = open(os.path.join(os.path.dirname(__file__), "..",
                                "extraction_utils.py"), encoding="utf-8").read()
        self.assertNotIn('"corner_cnt_clamped_to_rc_model": False', src)
        self.assertNotIn('"rc_model_corners": None', src)

    def test_single_corner_mode_disclaims_rc_rules_by_corner(self):
        src = open(os.path.join(os.path.dirname(__file__), "..",
                                "extraction_utils.py"), encoding="utf-8").read()
        self.assertIn("binding.rc_rules_by_corner is not consulted", src)


if __name__ == "__main__":
    unittest.main()
