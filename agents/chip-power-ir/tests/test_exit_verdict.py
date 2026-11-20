import contextlib
import importlib.util
import io
import json
import pathlib
import unittest
from unittest import mock


path = pathlib.Path(__file__).resolve().parents[1] / "tools" / "power-analysis" / "run.py"
spec = importlib.util.spec_from_file_location("power_runner", path)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ExitVerdictTests(unittest.TestCase):
    def check_exit(self, envelope, expected):
        output = io.StringIO()
        with mock.patch("builtins.open", return_value=io.StringIO(json.dumps(envelope))):
            with contextlib.redirect_stdout(output):
                self.assertEqual(runner._authoritative_exit_code("actual.json"), expected)
        self.assertEqual(json.loads(output.getvalue().split("CDE_JSON=", 1)[1]), envelope)

    def test_native_disconnected_pdn_review_is_nonzero(self):
        self.check_exit({
            "status": "completed",
            "validation": {"verdict": "review", "checks": {
                "functional_analysis": "not_assessable"}},
            "signoff_evidence": {"pdn_connectivity_ok": False,
                                "psm_error_codes": ["PSM-0038", "PSM-0039", "PSM-0069"]}
        }, 1)

    def test_pass_remains_success(self):
        self.check_exit({"status": "completed", "validation": {"verdict": "pass"}}, 0)

    def test_missing_verdict_is_not_success(self):
        self.check_exit({"status": "completed"}, 1)

    def test_nonpassing_verdicts_are_nonzero(self):
        for verdict in ("fail", "not_assessable", "blocked", "review", "unknown"):
            with self.subTest(verdict=verdict):
                self.check_exit({"status": "completed",
                                 "validation": {"verdict": verdict}}, 1)


if __name__ == "__main__":
    unittest.main()
