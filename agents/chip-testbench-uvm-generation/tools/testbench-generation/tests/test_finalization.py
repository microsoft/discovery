"""Synthetic evidence fixtures; these unit tests are not native chip signoff."""
import contextlib
import copy
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
utils = importlib.import_module("testbench_generation_utils")


class FinalizationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.params = {"scenario": "finalize_attempt", "evidence_refs": {}}
        generation = {
            "status": "completed", "validation": {"verdict": "pass"},
            "vplan": "synthetic-fixture",
            "results": {"smoke_failures": 0, "missing_vplan_linkage": 0,
                        "interface_mismatches": 0, "self_checking": True},
        }
        self.nonvacuity = {
            "status": "completed", "validation": {"verdict": "pass"},
            "results": {"mutants_killed": 1, "mutants_survived": 0},
            "qor_metrics": {"mutants_unassessable": 0, "testbench_vacuous": False},
        }
        for key, text in {
            "generation_cde": json.dumps(generation),
            "nonvacuity_cde": json.dumps(self.nonvacuity),
            "junit_xml": '<testsuite><testcase classname="dut" name="and"/></testsuite>',
            "junit_rerun_xml": '<testsuite><testcase classname="dut" name="and"/></testsuite>',
        }.items():
            path = self.root / key
            path.write_text(text, encoding="utf-8")
            self.params[key] = str(path)
            self.params["evidence_refs"][key] = "synthetic/" + key

    def execute(self, changed=None, legacy=False):
        nonvacuity = copy.deepcopy(self.nonvacuity)
        if changed:
            changed(nonvacuity)
        Path(self.params["nonvacuity_cde"]).write_text(json.dumps(nonvacuity), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            return (utils._finalize_attempt_legacy if legacy else utils._finalize_attempt)(self.params)

    def test_complete_native_evidence_closes_the_gate(self):
        result = self.execute()
        self.assertEqual(result["validation"]["verdict"], "pass", result.get("error"))
        self.assertTrue(result["progress"]["gate_closed"])
        self.assertEqual(result["stage"], "simulation")
        self.assertEqual(result["results"]["mutants_killed"]["value"], 1)

    def test_missing_or_malformed_nonvacuity_metrics_fail(self):
        cases = (None, -1, 0.5, True, "0", [], {})
        for field in ("mutants_unassessable", "testbench_vacuous"):
            for value in cases:
                with self.subTest(field=field, value=value):
                    result = self.execute(lambda env: env["qor_metrics"].update({field: value}))
                    self.assertEqual(result["validation"]["verdict"], "fail")
            with self.subTest(field=field, omitted=True):
                result = self.execute(lambda env: env["qor_metrics"].pop(field))
                self.assertEqual(result["validation"]["verdict"], "fail")

    def test_nonvacuous_flag_does_not_override_zero_kills_or_unassessable_runs(self):
        for group, field, value in (("results", "mutants_killed", 0),
                                     ("qor_metrics", "mutants_unassessable", 1),
                                     ("qor_metrics", "testbench_vacuous", True)):
            with self.subTest(field=field):
                result = self.execute(lambda env: env[group].update({field: value}))
                self.assertEqual(result["validation"]["verdict"], "fail")

    def test_changed_testcase_class_is_not_the_same_suite(self):
        Path(self.params["junit_rerun_xml"]).write_text(
            '<testsuite><testcase classname="other" name="and"/></testsuite>', encoding="utf-8")
        self.assertEqual(self.execute()["validation"]["verdict"], "fail")

    def test_legacy_entry_point_has_the_same_failure_gates(self):
        result = self.execute(lambda env: env["qor_metrics"].pop("mutants_unassessable"), legacy=True)
        self.assertEqual(result["validation"]["verdict"], "fail")
        self.assertNotIn("not defined", result.get("error", ""))

    def test_finalizer_records_missing_fields_without_an_undefined_smoke_variable(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = utils._finalize_envelope({"tool": utils.TOOL})
        self.assertIn("envelope_warnings", result)
        self.assertNotIn("CDE self-check skipped", output.getvalue())


if __name__ == "__main__":
    unittest.main()