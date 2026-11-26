import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import mock_open, patch


SOURCE = Path(__file__).resolve().parents[1] / "tools" / (
    "physical-integrity-checker") / "physical_integrity_checker_utils.py"
SPEC = importlib.util.spec_from_file_location("physical_openroad_utils", SOURCE)
UTILS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UTILS)


class OpenRoadEvidenceTest(unittest.TestCase):
    def test_nonzero_native_exit_retains_fresh_measured_violations_and_error(self):
        metric_checks = []

        def exists(path):
            if str(path).endswith("openroad_integrity_metrics.txt"):
                metric_checks.append(path)
                return len(metric_checks) > 1
            return True

        with patch("builtins.open", mock_open(read_data="illegal_overlaps=1\n")), patch.object(
                UTILS.os.path, "exists", side_effect=exists), patch.object(
                UTILS.shutil, "which", return_value="not-an-engine"), patch.object(
                UTILS.shutil, "copy2"), patch.object(
                UTILS.subprocess, "run", return_value=SimpleNamespace(
                    returncode=1, stdout="unit sentinel placement failure", stderr="")):
            metrics, error = UTILS._openroad_checks({"odb": str(SOURCE)}, {}, 500)
        self.assertEqual({"illegal_overlaps": 1}, metrics)
        self.assertIn("exited with code 1 after writing native measurements", error)
        self.assertIn("unit sentinel placement failure", error)

    def test_native_script_uses_bterm_net_and_never_zeros_unavailable_wire_lengths(self):
        writer = mock_open()
        with patch("builtins.open", writer), patch.object(
                UTILS.shutil, "which", return_value="not-an-engine"), patch.object(
                UTILS.shutil, "copy2"), patch.object(
                UTILS.subprocess, "run", return_value=SimpleNamespace(
                    returncode=1, stdout="unit sentinel native error", stderr="")):
            metrics, error = UTILS._openroad_checks({
                "def_file": str(SOURCE), "tech_lef": str(SOURCE),
                "cell_lef": [str(SOURCE)]}, {}, 500)
        self.assertEqual({}, metrics)
        self.assertIn("unit sentinel native error", error)
        script = writer().write.call_args_list[0].args[0]
        self.assertIn("set net [$bterm getNet]", script)
        self.assertIn("read_lef {", script)
        self.assertNotIn("read_lef -tech", script)
        self.assertNotIn("$bterm getITerms", script)
        self.assertIn("set long_wires_assessable 0", script)
        self.assertIn('if {$long_wires_assessable} { puts $fp "long_wires=$long_wires" }', script)


if __name__ == "__main__":
    unittest.main()
