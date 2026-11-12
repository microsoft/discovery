import json
import tempfile
import unittest
from pathlib import Path

import run
import functional_verification_utils as utils


class SourceContract(unittest.TestCase):
    def test_completed_fail_or_missing_verdict_does_not_exit_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cde.json"
            for verdict, expected in (("pass", 0), ("fail", 1), (None, 1)):
                path.write_text(json.dumps({"status": "completed",
                                            "validation": {"verdict": verdict}}))
                self.assertEqual(run._authoritative_exit_code(path), expected)

    def test_bad_explicit_input_never_falls_back(self):
        for value in ("[]", "null", "{broken", '{"scenario":"invented"}'):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                run.load_params([value])

    def test_source_paths_cannot_escape_input(self):
        for value in ("/etc/passwd", "/input/../etc/passwd"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run.load_params([json.dumps({"scenario": "run_sim", "rtl_files": [value]})])

    def test_exact_self_check_contract(self):
        clean = "COMPARISONS=8 MISMATCHES=0\nTEST PASSED\n"
        self.assertTrue(utils._self_check_evidence(clean, 0, 100)["passed"])
        cases = {
            "generic_success": clean.replace("TEST PASSED", "success"),
            "wrong_marker": clean.replace("TEST PASSED", "NOT TEST PASSED"),
            "missing_marker": clean.replace("TEST PASSED", ""),
            "partial_marker": clean.replace("TEST PASSED", "TEST PASSED-ish"),
            "missing_summary": "TEST PASSED\n",
            "duplicate_summary": clean + "COMPARISONS=8 MISMATCHES=0\n",
            "zero_comparisons": clean.replace("COMPARISONS=8", "COMPARISONS=0"),
            "nonzero_mismatches": clean.replace("MISMATCHES=0", "MISMATCHES=1"),
            "failure_overrides_pass": clean + "TEST FAILED\n",
            "error_overrides_pass": clean + "ERROR: bad result\n",
            "fatal_overrides_pass": clean + "FATAL: bad result\n",
        }
        for name, log in cases.items():
            with self.subTest(name=name):
                self.assertFalse(utils._self_check_evidence(log, 0, 100)["passed"])
        self.assertFalse(utils._self_check_evidence(clean, 1, 100)["passed"])
        self.assertFalse(utils._self_check_evidence(clean, 0, 0)["passed"])
        self.assertFalse(utils._self_check_evidence(clean, 0, 100, "ERROR: compile")["passed"])

    def test_relocated_references_match_native_files(self):
        with tempfile.TemporaryDirectory() as directory:
            old = utils._OUTPUT_DIR
            self.addCleanup(setattr, utils, "_OUTPUT_DIR", old)
            utils._OUTPUT_DIR = directory
            (Path(directory) / "wave.vcd").write_text("$enddefinitions $end\n")
            moves = utils._organize_output()
            refs = utils._relocate_output_refs({"vcd": "wave.vcd"}, moves)
            self.assertEqual(refs["vcd"], "results/wave.vcd")
            self.assertTrue((Path(directory) / refs["vcd"]).is_file())
            (Path(directory) / "wave.vcd").write_text("another wave")
            with self.assertRaises(FileExistsError):
                utils._organize_output()


if __name__ == "__main__":
    unittest.main()
