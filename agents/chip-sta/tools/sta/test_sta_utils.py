import unittest

import sta_utils


class SignoffPopulationTests(unittest.TestCase):
    def test_happy_path(self):
        log = """
__CLOCK_PROPAGATION__ clocks=1 status=executed
__ENDPOINT_COVERAGE__ sequential=96 outputs=49 timing_total=145 input_startpoints=15 constrained_total=160
__CHECK_SETUP__
Warning: There are 0 unconstrained endpoints.
"""
        result = sta_utils._parse_signoff_population(log, 145, 15, 160, 0)
        self.assertEqual(result["timing_endpoint_count"], 145)
        self.assertEqual(result["input_startpoint_count"], 15)
        self.assertEqual(result["constrained_object_count"], 160)
        self.assertTrue(result["timing_endpoint_count_matches"])
        self.assertTrue(result["input_startpoint_count_matches"])
        self.assertTrue(result["constrained_object_count_matches"])
        self.assertTrue(result["population_identity_matches"])
        self.assertTrue(result["unconstrained_count_matches"])

    def test_missing_or_unexecuted_blocks_fail_closed(self):
        for log in ("", "__CLOCK_PROPAGATION__ clocks=1 status=executed"):
            result = sta_utils._parse_signoff_population(log, 145, 15, 160, 0)
            self.assertIsNone(result)
            self.assertIsNotNone(
                sta_utils._signoff_population_blocker(result))

    def test_population_mismatch_fails_closed(self):
        log = """
__CLOCK_PROPAGATION__ clocks=1 status=executed
__ENDPOINT_COVERAGE__ sequential=95 outputs=49 timing_total=144 input_startpoints=15 constrained_total=159
__CHECK_SETUP__
Warning: There are 1 unconstrained endpoints.
"""
        result = sta_utils._parse_signoff_population(log, 145, 15, 160, 0)
        self.assertIn(
            "SIGNOFF POPULATION MISMATCH",
            sta_utils._signoff_population_blocker(result))

    def test_empty_clock_population_fails_closed(self):
        log = """
__CLOCK_PROPAGATION__ clocks=0 status=executed
__ENDPOINT_COVERAGE__ sequential=96 outputs=49 timing_total=145 input_startpoints=15 constrained_total=160
__CHECK_SETUP__
Warning: There are 0 unconstrained endpoints.
"""
        result = sta_utils._parse_signoff_population(log, 145, 15, 160, 0)
        self.assertIn(
            "empty clock population",
            sta_utils._signoff_population_blocker(result))

    def test_empty_drv_block_is_not_clean(self):
        self.assertEqual(
            sta_utils._parse_drv_violators(""),
            (0, None, False))

    def test_unrecognized_drv_block_is_not_clean(self):
        self.assertEqual(
            sta_utils._parse_drv_violators("command did not execute"),
            (0, None, False))

    def test_clean_drv_block_is_numeric(self):
        self.assertEqual(
            sta_utils._parse_drv_violators("No paths found."),
            (0, None, True))

    def test_affirmative_clean_zero(self):
        measure = """
Pin                                    Limit    Slew   Slack
------------------------------------------------------------
_430_/SCE                               1.40    0.75    0.65 (MET)
"""
        self.assertEqual(
            sta_utils._parse_drv_affirmative_evidence(measure, ""),
            (0, 0.65, True))

    def test_affirmative_real_violations(self):
        measure = """
Pin                                    Limit    Slew   Slack
------------------------------------------------------------
_430_/SCE                               1.40    1.75   -0.35 (VIOLATED)
"""
        violators = """
Pin                                    Limit    Slew   Slack
------------------------------------------------------------
_430_/SCE                               1.40    1.75   -0.35 (VIOLATED)
_431_/SCE                               1.40    1.60   -0.20 (VIOLATED)
"""
        self.assertEqual(
            sta_utils._parse_drv_affirmative_evidence(measure, violators),
            (2, -0.35, True))

    def test_affirmative_missing_partial_or_malformed_fails_closed(self):
        good = "_430_/SCE 1.40 0.75 0.65 (MET)"
        cases = (
            ("", ""),
            (good, None),
            ("command did not execute", ""),
            ("_430_/SCE no numeric result (MET)", ""),
            (good, "_431_/SCE 1.40 1.75 -0.35 (VIOLATED)"),
        )
        for measure, violators in cases:
            with self.subTest(measure=measure, violators=violators):
                self.assertEqual(
                    sta_utils._parse_drv_affirmative_evidence(
                        measure, violators),
                    (0, None, False))


if __name__ == "__main__":
    unittest.main()
