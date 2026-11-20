import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock

path = Path(__file__).resolve().parents[1] / "dse_optimization_utils.py"
spec = importlib.util.spec_from_file_location("validated_dse", path)
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)


class ValidatedSources(unittest.TestCase):
    def setUp(self):
        self.source = Path(__file__).with_name("unit-source-cde.json")
        self.cde = {"status": "completed", "validation": {"verdict": "pass"},
                    "progress": {"gate_closed": True}, "qor_metrics": {"cell_count": 4}}
        self.point = {"config": {"fixture": "unit"}, "source_cde": str(self.source),
                      "metrics": {"cell_count": 4}}
        self.params = {"points": [self.point], "objectives": [{"metric": "cell_count", "goal": "min"}]}
        self.write_source()
        self.output = mock.patch.object(utils, "_OUTPUT_DIR", str(self.source.parent))
        self.output.start()

    def write_source(self):
        self.source.write_text(json.dumps(self.cde), encoding="utf-8")
        self.point["source_cde_sha256"] = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def tearDown(self):
        self.output.stop()
        self.source.unlink(missing_ok=True)
        self.source.with_name("pareto.json").unlink(missing_ok=True)

    def test_closed_source_runs_actual_search(self):
        result = utils._explore(self.params)
        self.assertEqual(result["validation"]["verdict"], "pass")
        self.assertEqual(result["results"]["explored"]["value"], 1)
        self.assertEqual(result["qor_metrics"]["recommended_metrics"], {"cell_count": 4})

    def test_open_gate_never_recommends(self):
        self.cde["progress"]["gate_closed"] = False
        self.write_source()
        result = utils._explore(self.params)
        self.assertEqual(result["validation"]["verdict"], "not_assessable")
        self.assertIsNone(result["qor_metrics"]["recommended_recipe"])

    def test_failed_or_unassessed_source_never_recommends(self):
        for verdict in ("fail", "not_assessable", "review"):
            self.cde["validation"]["verdict"] = verdict
            self.write_source()
            self.assertEqual(utils._explore(self.params)["validation"]["verdict"], "not_assessable")

    def test_hash_is_required_and_checked(self):
        self.point["source_cde_sha256"] = "wrong"
        result = utils._explore(self.params)
        self.assertEqual(result["validation"]["verdict"], "fail")
        self.assertIsNone(result["qor_metrics"]["recommended_metrics"])

    def test_invented_metric_is_rejected(self):
        self.point["metrics"]["cell_count"] = 3
        result = utils._explore(self.params)
        self.assertEqual(result["validation"]["verdict"], "fail")
        self.assertIsNone(result["qor_metrics"]["recommended_recipe"])

    def test_budget_failure_has_no_fallback_recommendation(self):
        self.params["budget"] = {"cell_count": 0}
        result = utils._explore(self.params)
        self.assertEqual(result["validation"]["verdict"], "fail")
        self.assertIsNone(result["qor_metrics"]["recommended_recipe"])

    def test_nonfinite_metric_is_not_rankable(self):
        self.cde["qor_metrics"]["cell_count"] = float("nan")
        self.point["metrics"]["cell_count"] = float("nan")
        self.write_source()
        self.assertEqual(utils._explore(self.params)["validation"]["verdict"], "fail")
