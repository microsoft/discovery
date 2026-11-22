import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "tools/power-intent-upf"
sys.path.insert(0, str(SOURCE))
SPEC = importlib.util.spec_from_file_location("upf_reader_test", SOURCE / "power_intent_upf_utils.py")
upf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(upf)


class ReaderContractTest(unittest.TestCase):
    def test_unknown_command_is_not_assumed_standard(self):
        self.assertEqual(upf._classify_upf_line(
            "create_power_domian PD", 'invalid command name "create_power_domian"'), "rejected")

    def test_known_unimplemented_command_remains_unverified(self):
        self.assertEqual(upf._classify_upf_line(
            "create_supply_net VDD", 'invalid command name "create_supply_net"'),
            "unsupported_by_reader")

    def test_marker_does_not_override_exit_or_error(self):
        self.assertEqual(upf._classify_upf_line("create_power_domain PD", "@@UPF_OK@@", 1),
                         "rejected")
        self.assertEqual(upf._classify_upf_line(
            "create_power_domain PD", "[ERROR UPF-0001] rejected\n@@UPF_OK@@"), "rejected")

    def check_file(self, text, outputs):
        with tempfile.TemporaryDirectory() as directory:
            completed = [SimpleNamespace(returncode=code, stdout=out, stderr="")
                         for code, out in outputs]
            with patch.object(upf, "_WORK_DIR", directory), patch.object(
                    upf, "_OUTPUT_DIR", directory), patch.object(
                    upf.shutil, "which", return_value="openroad"), patch.object(
                    upf, "_upf_design_context", return_value=("read_def test.def\n", "test context")
                    ), patch.object(upf.subprocess, "run", side_effect=completed) as reader:
                result = upf._validate_upf({"upf": text})
            self.assertEqual(reader.call_count, len(outputs))
            self.assertTrue((Path(directory) / "upf_complete_read.log").is_file())
            return result

    def test_partial_reader_coverage_is_not_pass(self):
        result = self.check_file("create_power_domain PD\ncreate_supply_net VDD", [
            (0, "@@UPF_OK@@"), (1, 'invalid command name "create_supply_net"'),
            (1, 'invalid command name "create_supply_net"')])
        self.assertEqual(result["validation"]["verdict"], "not_assessable")

    def test_independent_lines_do_not_prove_complete_file(self):
        result = self.check_file("create_power_domain PD\ncreate_power_domain PD", [
            (0, "@@UPF_OK@@"), (0, "@@UPF_OK@@"),
            (1, "[ERROR UPF-0001] duplicate domain")])
        self.assertEqual(result["validation"]["verdict"], "fail")

    def test_supported_complete_file_passes_only_reader_scope(self):
        result = self.check_file("create_power_domain PD", [
            (0, "@@UPF_OK@@"), (0, "@@UPF_OK@@")])
        self.assertEqual(result["validation"]["verdict"], "pass")
        self.assertTrue(result["signoff_evidence"]["complete_file_read"]["accepted"])
        self.assertEqual(result["provenance"]["engine"], "OpenROAD read_upf")

    def test_complete_file_preserves_tcl_context(self):
        result = self.check_file("set name PD\ncreate_power_domain $name", [
            (0, "@@UPF_OK@@"), (1, 'can\'t read "name": no such variable'),
            (0, "@@UPF_OK@@")])
        self.assertEqual(result["validation"]["verdict"], "pass")
        self.assertEqual(result["qor_metrics"]["commands_accepted"], 1)


if __name__ == "__main__":
    unittest.main()
