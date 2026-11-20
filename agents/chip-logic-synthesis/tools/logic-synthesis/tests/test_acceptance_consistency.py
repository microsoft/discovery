import importlib.util
from pathlib import Path
import types
import unittest
from unittest import mock

path = Path(__file__).resolve().parents[1] / "logic_synthesis_utils.py"
spec = importlib.util.spec_from_file_location("acceptance_synthesis", path)
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)


class AcceptanceConsistency(unittest.TestCase):
    def test_open_acceptance_cannot_remain_a_pass(self):
        def stamp(result, stage):
            result["progress"] = {
                "gate_closed": False,
                "verdict_normalized": result["validation"]["verdict"],
                "alignment_severity": "blocking" if result["validation"]["verdict"] == "pass" else "advisory",
                "alignment_detail": "area acceptance evidence absent",
            }

        result = {"tool": "logic-synthesis", "status": "completed",
                  "validation": {"verdict": "pass"}, "results": {}}
        with mock.patch.dict("sys.modules", {"cde_progress": types.SimpleNamespace(stamp_progress=stamp)}):
            result = utils._finalize_envelope(result)
        self.assertEqual(result["validation"]["verdict"], "not_assessable")
        self.assertFalse(result["progress"]["gate_closed"])
        self.assertEqual(result["validation"]["execution_verdict_before_acceptance_check"], "pass")
        self.assertIn("unclosed_acceptance_contract", result["signoff_evidence"])

    def test_domain_failure_is_not_relabelled(self):
        result = {"tool": "logic-synthesis", "status": "failed",
                  "validation": {"verdict": "fail"}, "results": {}}
        with mock.patch.dict("sys.modules", {"cde_progress": types.SimpleNamespace(
                stamp_progress=lambda result, stage: result.update(
                    progress={"gate_closed": False, "alignment_severity": "blocking"}))}):
            self.assertEqual(utils._finalize_envelope(result)["validation"]["verdict"], "fail")
