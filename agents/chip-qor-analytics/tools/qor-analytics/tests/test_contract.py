import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import capability_check
import qor_analytics_utils as utils
import qor_stats
import run


def params(scenario="anomaly_detect", metric="wns", values=(-0.5,)):
    return {"scenario": scenario, "metrics": [metric], "baseline": {metric: -1},
            "envelopes": [{"id": "run." + str(i), "order": i, "corner": "tt",
                           "design": "demo", "pdk": "sky130", "tool_version": "1",
                           "metrics": {metric: value}}
                          for i, value in enumerate(values)]}


class ContractTests(unittest.TestCase):
    def test_capability(self):
        capability_check.main()

    def test_improvement(self):
        r = utils.dispatch(params())
        self.assertEqual(r["validation"]["verdict"], "pass")
        self.assertEqual(r["results"]["improvements"]["value"], 1)

    def test_regression(self):
        p = params(metric="area_um2", values=(120,))
        p["baseline"] = {"area_um2": 100}
        self.assertEqual(utils.dispatch(p)["validation"]["verdict"], "fail")

    def test_unknown_polarity(self):
        p = params(metric="frobnication", values=(10,))
        p["baseline"] = {"frobnication": 5}
        self.assertEqual(utils.dispatch(p)["validation"]["verdict"], "not_assessable")

    def test_declared_polarity(self):
        p = params(metric="frobnication", values=(10,))
        p["baseline"] = {"frobnication": 5}
        p["metric_polarity"] = {"frobnication": "max"}
        self.assertEqual(utils.dispatch(p)["validation"]["verdict"], "pass")

    def test_missing_context(self):
        p = params()
        p["envelopes"] = [{"id": "r", "metrics": {"wns": -0.5}}]
        self.assertEqual(utils.dispatch(p)["validation"]["verdict"], "not_assessable")

    def test_conflicting_context(self):
        p = params(values=(-0.5, -0.4))
        p["envelopes"][1]["corner"] = "ff"
        self.assertEqual(utils.dispatch(p)["validation"]["verdict"], "fail")

    def test_empty_anomaly(self):
        p = params(values=())
        self.assertEqual(utils.dispatch(p)["validation"]["verdict"], "fail")

    def test_absent_measurements(self):
        p = params()
        p["metrics"] = ["area_um2"]
        self.assertEqual(utils.dispatch(p)["validation"]["verdict"], "not_assessable")

    def test_two_points(self):
        p = params("trajectory", values=(-0.5, -0.4))
        self.assertEqual(utils.dispatch(p)["validation"]["verdict"], "not_assessable")

    def test_strong_improving_trend(self):
        r = utils.dispatch(params("trajectory", values=(-0.9, -0.6, -0.3)))
        self.assertEqual(r["validation"]["verdict"], "pass")
        self.assertEqual(r["qor_metrics"]["wns"]["r_squared"], 1)

    def test_strong_degrading_trend(self):
        r = utils.dispatch(params("trajectory", "area_um2", (100, 110, 120)))
        self.assertEqual(r["validation"]["verdict"], "fail")

    def test_unclassified_trend(self):
        r = utils.dispatch(params("trajectory", "frobnication", (100, 110, 120)))
        self.assertEqual(r["validation"]["verdict"], "not_assessable")
        t = r["signoff_evidence"]["trajectories"]["frobnication"]
        self.assertFalse(t["assessable"])
        self.assertIsNone(t["slope_per_run"])
        self.assertEqual(t["diagnostic_fit"]["slope_per_run"], 10)

    def test_partial_anomaly_measurements(self):
        p = params(values=(-0.5, -0.4))
        p["envelopes"][1]["metrics"] = {}
        self.assertEqual(utils.dispatch(p)["validation"]["verdict"], "not_assessable")

    def test_missing_requested_baseline(self):
        p = params()
        p["baseline"] = {"area_um2": 100}
        self.assertEqual(utils.dispatch(p)["validation"]["verdict"], "not_assessable")

    def test_partial_context(self):
        p = params(values=(-0.5, -0.4))
        p["envelopes"][1].pop("corner")
        self.assertEqual(utils.dispatch(p)["validation"]["verdict"], "not_assessable")

    def test_incomplete_cohort_identity(self):
        self.assertIsNone(qor_stats.comparability([{"corner": "tt"}])["comparable"])

    def test_partial_trend(self):
        p = params("trajectory", values=(-0.9, -0.6, -0.3))
        p["metrics"].append("area_um2")
        for e in p["envelopes"][:2]:
            e["metrics"]["area_um2"] = 100
        r = utils.dispatch(p)
        self.assertEqual(r["validation"]["verdict"], "not_assessable")
        self.assertIsNone(r["qor_metrics"]["area_um2"]["slope_per_run"])
        self.assertAlmostEqual(r["qor_metrics"]["wns"]["slope_per_run"], 0.3)

    def test_unordered_trend_is_diagnostic_only(self):
        p = params("trajectory", values=(-0.9, -0.6, -0.3))
        for e in p["envelopes"]:
            e.pop("order")
        r = utils.dispatch(p)
        self.assertEqual(r["validation"]["verdict"], "not_assessable")
        self.assertIsNone(r["qor_metrics"]["wns"]["slope_per_run"])
        self.assertAlmostEqual(r["signoff_evidence"]["trajectories"]["wns"]["diagnostic_fit"]["slope_per_run"], 0.3)

    def test_missing_explicit_order_key(self):
        p = params("trajectory", values=(-0.9, -0.6, -0.3))
        p["order_key"] = "sequence"
        self.assertEqual(utils.dispatch(p)["validation"]["verdict"], "not_assessable")

    def test_duplicate_order(self):
        p = params("trajectory", values=(-0.9, -0.6, -0.3))
        p["envelopes"][1]["order"] = 0
        self.assertEqual(utils.dispatch(p)["validation"]["verdict"], "not_assessable")

    def test_unknown_subthreshold_change_diagnostic(self):
        p = params(metric="frobnication", values=(101,))
        p["baseline"] = {"frobnication": 100}
        self.assertEqual(utils.dispatch(p)["validation"]["verdict"], "pass")

    def test_descriptive_stats_do_not_need_polarity(self):
        candidates = utils._inline_candidates({"frobnication": 100})
        self.assertEqual(utils._resolve_metric("frobnication", candidates)[0], 100)

    def test_sparse_sample_size(self):
        t = qor_stats.trajectory([{"id": "a", "area": 1}, {"id": "b"},
                                  {"id": "c", "area": 3}], "area")
        self.assertEqual((t["n_used"], t["n_runs"], t["assessable"]), (2, 3, False))

    def test_invalid_contracts(self):
        cases = [[], {}, {"mode": "aggregate"}, {"scenario": "compare"},
                 {**params(), "metrics": "wns"}, {**params(), "envelopes": {}},
                 {**params(), "pdk_binding": "{}"}, {**params(), "sigma": True},
                 {**params(), "baseline": {"wns": float("inf")}},
                 {**params(), "metric_polarity": {"wns": "up"}},
                 {**params(), "envelopes": ["/etc/passwd"]}]
        for p in cases:
            with self.subTest(p=p), self.assertRaises(ValueError):
                run._validate_params(p)

    def test_strict_json(self):
        for raw in ('{"scenario":"aggregate","scenario":"trajectory"}',
                    '{"scenario":"aggregate","envelopes":[],"sigma":NaN}',
                    "[]", "{bad}"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                run.load_params([raw])

    def test_parameter_path_escape(self):
        with self.assertRaises(ValueError):
            run.load_params(["--params-file", "/input/../etc/params.json"])

    def test_text_preservation(self):
        p = params()
        p["envelopes"][0]["id"] = "designer's \u201cchip\u201d"
        loaded = run.load_params([json.dumps(p)])
        self.assertEqual(loaded, p)

    def test_legacy_percent_floor(self):
        p = params()
        p["sigma"] = 3
        r = utils.dispatch(p)
        self.assertEqual(r["signoff_evidence"]["threshold_percent"], 5)
        self.assertIn("legacy", r["signoff_evidence"]["threshold_parameter_used"])

    def test_family_conversion(self):
        candidates = utils._cde_candidates({"results": {"worst_slack": {"value": -500, "unit": "ps"}}})
        value, source = utils._resolve_metric("wns_ns", candidates)
        self.assertEqual(value, -0.5)
        self.assertTrue(source["converted"])


if __name__ == "__main__":
    unittest.main()
