import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run
import rtl_lint_utils as utils


class SourceContract(unittest.TestCase):
    def test_completed_fail_and_diagnostic_subchecks_do_not_exit_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cde.json"
            for verdict, expected in (("pass", 0), ("fail", 1), (None, 1),
                                      ("not_assessable", 1)):
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
                run.load_params([json.dumps({"scenario": "lint_gate", "sources": [value]})])

    def test_relocated_references_match_native_files(self):
        with tempfile.TemporaryDirectory() as directory:
            old = utils._OUTPUT_DIR
            self.addCleanup(setattr, utils, "_OUTPUT_DIR", old)
            utils._OUTPUT_DIR = directory
            (Path(directory) / "verible_lint.log").write_text("native log")
            moved = utils._organize_output()
            refs = utils._relocate_output_refs({"log": "verible_lint.log"}, moved)
            self.assertEqual(refs["log"], "logs/verible_lint.log")
            self.assertTrue((Path(directory) / refs["log"]).is_file())
            (Path(directory) / "verible_lint.log").write_text("another log")
            with self.assertRaises(FileExistsError):
                utils._organize_output()


if __name__ == "__main__":
    unittest.main()
