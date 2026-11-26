import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "tools/lvs/lvs_utils.py"
SPEC = importlib.util.spec_from_file_location("lvs_utils", SOURCE)
lvs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lvs)


class NetgenPropertiesTest(unittest.TestCase):
    def test_unique_topology_does_not_hide_width_error(self):
        report = (
            "Circuits match uniquely.\nProperty errors were found.\n"
            " w circuit1: 0.65   circuit2: 1.3   (delta=66.7%, cutoff=1%)\n"
        )
        self.assertEqual(lvs._property_mismatch_count(report + report), 1)

    def test_summary_without_details_remains_nonzero(self):
        self.assertEqual(lvs._property_mismatch_count(
            "Netlists match uniquely.\nThere were property errors.\n"), 1)

    def test_clean_report(self):
        self.assertEqual(lvs._property_mismatch_count(
            "Circuits match uniquely.\nCell pin lists are equivalent.\n"), 0)

    def test_legacy_property_mismatch(self):
        self.assertEqual(lvs._property_mismatch_count(
            "Property mismatch: width\nDevice classes differ\n"), 2)

    def test_compare_rejects_property_errors_and_nonzero_engine_exit(self):
        for suffix, code, verdict in (
                ("", 0, "pass"),
                ("\nProperty errors were found.\n", 0, "fail"),
                ("", 1, "fail")):
            with self.subTest(suffix=suffix, code=code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in ("layout.ext.spice", "source.cdl"):
                    (root / name).write_text(".subckt TOP A Y\n.ends\n")
                with patch.object(lvs, "_WORK_DIR", directory), patch.object(
                        lvs, "_OUTPUT_DIR", directory), patch.object(
                        lvs, "_netgen_bin", return_value="netgen"), patch.object(
                        lvs, "_version", return_value="Netgen test double"), patch.object(
                        lvs.subprocess, "run", return_value=SimpleNamespace(
                            returncode=code, stdout="Circuits match uniquely.\n" + suffix,
                            stderr="")):
                    result = lvs._lvs_compare({
                        "layout_netlist": str(root / "layout.ext.spice"),
                        "schematic_netlist": str(root / "source.cdl"),
                        "top": "TOP", "setup": "nosetup",
                        "pdk_binding": {}})
                self.assertEqual(result["validation"]["verdict"], verdict)
                if code:
                    self.assertEqual(result["status"], "failed")
                    self.assertNotIn("lvs_match", result["results"])
                else:
                    self.assertEqual(result["results"]["lvs_match"]["value"], verdict == "pass")
                script = (root / "lvs_compare.tcl").read_text()
                self.assertEqual(script.count("readnet spice"), 2)


if __name__ == "__main__":
    unittest.main()
