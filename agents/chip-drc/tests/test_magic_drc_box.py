import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "drc"))
import drc_utils  # noqa: E402

HEAD = "Reading \"TOP\".\nLoading DRC CIF style.\n"


def fake(stdout):
    return types.SimpleNamespace(stdout=stdout, stderr="", returncode=0)


class MagicDrcBoxTests(unittest.TestCase):
    def run_with(self, stdout):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(drc_utils, "_OUTPUT_DIR", tmp), \
                mock.patch.object(drc_utils, "_WORK_DIR", tmp), \
                mock.patch.object(drc_utils, "_magic_bin", return_value="magic"), \
                mock.patch.object(drc_utils, "_magic_version", return_value="magic 8.3.693"), \
                mock.patch.object(drc_utils, "_save_run_command", lambda cmd: None), \
                mock.patch.object(drc_utils.subprocess, "run", return_value=fake(stdout)) as run:
            result = drc_utils._run_magic_drc({}, "/x/top.gds", "TOP", {})
            script = Path(tmp, "magic_drc.tcl").read_text()
        return result, script, run

    def test_script_selects_top_cell_before_drc_check(self):
        _, script, _ = self.run_with(HEAD + "MAGIC_DRC_BOX 0 0 10 10\nMAGIC_DRC_COUNT 0\n"
                                     "MAGIC_DRC_WHY_BEGIN\nMAGIC_DRC_WHY_END\n")
        self.assertLess(script.index("select top cell"), script.index("drc check"))

    def test_violation_is_counted_per_rule(self):
        result, _, _ = self.run_with(
            HEAD + "MAGIC_DRC_BOX 0 0 1000 500\nMAGIC_DRC_COUNT 1\nMAGIC_DRC_WHY_BEGIN\n"
            "MAGIC_DRC_RULE 1\tMetal1 width < 0.14um (met1.1)\nMAGIC_DRC_WHY_END\n")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["per_rule"], {"Metal1 width < 0.14um (met1.1)": 1})

    def test_missing_box_is_unmeasured_not_clean(self):
        result, _, _ = self.run_with(HEAD + "Box tool must be present\nMAGIC_DRC_BOX \n"
                                     "MAGIC_DRC_COUNT 0\nMAGIC_DRC_WHY_BEGIN\nMAGIC_DRC_WHY_END\n")
        self.assertFalse(result["ok"])
        self.assertIsNone(result["count"])
        self.assertIn("checked nothing", result["error"])

    def test_zero_count_with_listed_violations_is_inconsistent(self):
        result, _, _ = self.run_with(
            HEAD + "MAGIC_DRC_BOX 0 0 1000 500\nMAGIC_DRC_COUNT 0\nMAGIC_DRC_WHY_BEGIN\n"
            "MAGIC_DRC_RULE 2\tMetal1 spacing < 0.14um (met1.2)\nMAGIC_DRC_WHY_END\n")
        self.assertFalse(result["ok"])
        self.assertIsNone(result["count"])
        self.assertIn("internally inconsistent", result["error"])


if __name__ == "__main__":
    unittest.main()
