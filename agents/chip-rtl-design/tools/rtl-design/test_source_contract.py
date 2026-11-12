import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run
import rtl_design_utils as utils


class SourceContract(unittest.TestCase):
    def test_completed_fail_and_missing_verdict_do_not_exit_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cde.json"
            for verdict, expected in (("pass", 0), ("fail", 1), (None, 1),
                                      ("not_assessable", 1), ("pass_with_caveats", 1)):
                path.write_text(json.dumps({"status": "completed",
                                            "validation": {"verdict": verdict}}))
                self.assertEqual(run._authoritative_exit_code(path), expected)

    def test_bad_explicit_input_never_falls_back(self):
        for value in ("[]", "null", "{broken", '{"scenario":"invented"}'):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                run.load_params([value])

    def test_inline_rtl_apostrophes_survive(self):
        params = {"scenario": "check_authored", "top": "dut",
                  "rtl": "module dut(output y); assign y = 1'b0; endmodule"}
        self.assertEqual(run.load_params([json.dumps(params)]), params)

    def test_source_paths_cannot_escape_input(self):
        for value in ("/etc/passwd", "/input/../etc/passwd"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run.load_params([json.dumps({"scenario": "check_authored", "top": "dut",
                                             "rtl_files": [value]})])

    def test_missing_formatter_cannot_pass_hygiene(self):
        for source in ({"rtl": "module dut; endmodule"},
                       {"rtl_files": ["/input/dut.v"]}):
            with self.subTest(source=source), \
                    mock.patch.object(utils, "_formatter_binary", return_value=None), \
                    mock.patch.object(utils, "_lint_hygiene") as hygiene:
                result = utils._check_authored({"top": "dut", **source})
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["validation"]["verdict"], "fail")
                self.assertIn("not found", result["error"])
                hygiene.assert_not_called()

    def test_relocated_references_match_native_files(self):
        with tempfile.TemporaryDirectory() as directory:
            old = utils._OUTPUT_DIR
            self.addCleanup(setattr, utils, "_OUTPUT_DIR", old)
            utils._OUTPUT_DIR = directory
            (Path(directory) / "yosys.log").write_text("native log")
            moved = utils._organize_output()
            refs = utils._relocate_output_refs({"log": "yosys.log"}, moved)
            self.assertEqual(refs["log"], "logs/yosys.log")
            self.assertTrue((Path(directory) / refs["log"]).is_file())
            (Path(directory) / "yosys.log").write_text("another log")
            with self.assertRaises(FileExistsError):
                utils._organize_output()


if __name__ == "__main__":
    unittest.main()
