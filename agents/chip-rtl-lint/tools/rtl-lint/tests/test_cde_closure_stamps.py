"""Every rtl-lint CDE must carry a root verdict and hand task identity to the host.

Guards tickets/lint/mytop4-hiersoc-crc16_ccitt-lint-tool-output-needs-manual-
closure-stamps.md: the tool recorded its verdict ONLY under `validation.verdict`,
so `catalog/finalize_cde.py` -- which reads the ROOT and refuses by design to
invent one -- failed closure on every attempt and cost a hand-repair cycle each
time.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import rtl_lint_utils


class TestRootVerdict(unittest.TestCase):
    def test_root_verdict_mirrors_validation_verdict(self):
        for verdict in ("pass", "fail", "review", "not_assessable"):
            env = rtl_lint_utils._cde(objective="o", status="completed",
                                      validation={"verdict": verdict})
            self.assertEqual(env["verdict"], verdict)
            self.assertEqual(env["validation"]["verdict"], verdict)

    def test_root_verdict_present_even_with_no_validation_supplied(self):
        env = rtl_lint_utils._cde(objective="o", status="failed")
        self.assertEqual(env["verdict"], "review")

    def test_error_envelope_still_carries_a_root_verdict(self):
        env = rtl_lint_utils._cde(objective="o", status="failed",
                                  error="boom", validation={"verdict": "fail"})
        self.assertEqual(env["verdict"], "fail")
        self.assertEqual(env["error"], "boom")


class TestTaskIdentityHandoff(unittest.TestCase):
    def test_clean_envelope_declares_host_finalization(self):
        env = rtl_lint_utils._cde(objective="o", status="completed",
                                  validation={"verdict": "pass"})
        self.assertEqual(env["provenance"]["task_identity_state"],
                         "host_finalization_required")
        self.assertEqual(env["provenance"]["task_identity_authority"],
                         "catalog/stage_task_identity.canonical_stamp")

    def test_tool_supplied_identity_fails_closed(self):
        for field in ("run_id", "task_uuid", "task_dx_id",
                      "task_identity_sha256"):
            env = rtl_lint_utils._cde(objective="o", status="completed",
                                      validation={"verdict": "pass"},
                                      provenance={field: "invented"})
            self.assertEqual(env["status"], "failed", field)
            self.assertEqual(env["verdict"], "fail", field)
            self.assertEqual(env["validation"]["verdict"], "fail", field)
            self.assertFalse(env["validation"]["stage_closure_eligible"], field)
            self.assertEqual(env["provenance"]["task_identity_state"],
                             "rejected_untrusted_tool_stamp", field)
            self.assertIn(field, env["error"])

    def test_supplied_provenance_is_not_mutated_in_place(self):
        supplied = {"verible": "v0.0-test"}
        rtl_lint_utils._cde(objective="o", status="completed",
                            validation={"verdict": "pass"},
                            provenance=supplied)
        self.assertEqual(supplied, {"verible": "v0.0-test"})


if __name__ == "__main__":
    unittest.main()
