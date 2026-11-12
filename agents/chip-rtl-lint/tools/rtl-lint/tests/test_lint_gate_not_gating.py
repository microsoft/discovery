"""lint_gate must be able to express pass with formatting/style not_gating.

Guards DX-38 (origin DX-35): lint_gate hard-coded format as a gating family and
forced write_formatted=True, so it could never pass on golden RTL whose
reformatting is forbidden.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import rtl_lint_utils as u


def _lint_env(rules):
    return {"status": "completed",
            "results": {"lint_violations": {"value": sum(rules.values())}},
            "signoff_evidence": {"rules": rules}}


def _fmt_env(n):
    return {"status": "completed",
            "results": {"unformatted_files": {"value": n}},
            "signoff_evidence": {"unformatted_files": ["a.v"] * n,
                                 "format_proposals": [], "proposal_errors": []}}


class TestLintGateNotGating(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "a.v")
        with open(self.src, "w") as f:
            f.write("module a; endmodule\n")
        u._OUTPUT_DIR = self.tmp.name

    def _run(self, rules, fmt, **extra):
        seen = {}

        def fake_format(p):
            seen.update(p)
            return _fmt_env(fmt)

        params = {"scenario": "lint_gate", "sources": [self.src], **extra}
        with mock.patch.object(u, "_lint", return_value=_lint_env(rules)), \
                mock.patch.object(u, "_format", side_effect=fake_format):
            return u._lint_gate(params), seen

    def test_default_unchanged_format_gates(self):
        env, seen = self._run({}, 3)
        self.assertEqual(env["verdict"], "fail")
        self.assertTrue(seen["write_formatted"])

    def test_format_not_gating_passes_without_proposals(self):
        env, seen = self._run({}, 3, format_gating=False)
        self.assertEqual(env["verdict"], "pass")
        self.assertTrue(env["validation"]["stage_closure_eligible"])
        self.assertFalse(seen["write_formatted"])
        self.assertEqual(env["results"]["unformatted_files"]["class"],
                         "not_gating")
        self.assertNotIn("format", env["signoff_evidence"]["required_families"])

    def test_declared_style_rules_reported_separately(self):
        rules = {"no-trailing-spaces": 5, "line-length": 2}
        env, _ = self._run(rules, 1, format_gating=False,
                           style_rules=["no-trailing-spaces", "-line-length"])
        self.assertEqual(env["verdict"], "pass")
        self.assertEqual(env["results"]["lint_violations"]["value"], 0)
        self.assertEqual(env["results"]["style_violations"]["value"], 7)
        self.assertEqual(env["results"]["style_violations"]["class"],
                         "not_gating")

    def test_semantic_finding_still_fails(self):
        env, _ = self._run({"no-trailing-spaces": 5, "explicit-function-lifetime": 1},
                           0, format_gating=False,
                           style_rules=["no-trailing-spaces"])
        self.assertEqual(env["verdict"], "fail")
        self.assertEqual(env["results"]["lint_violations"]["value"], 1)

    def test_undeclared_style_stays_gating(self):
        env, _ = self._run({"no-trailing-spaces": 5}, 0)
        self.assertEqual(env["verdict"], "fail")

    def test_syntax_error_cannot_be_style(self):
        env, _ = self._run({}, 0, style_rules=["syntax-error-or-unclassified"])
        self.assertEqual(env["status"], "failed")
        self.assertEqual(env["verdict"], "fail")


if __name__ == "__main__":
    unittest.main()
