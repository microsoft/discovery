"""Local CPU regression tests; run with unittest discovery and NumPy installed."""

import copy
import json
import unittest

import numpy as np

from alchemi_validators import (audit_hook_events, compare_numeric,
                                independent_energy_drift, independent_kinetic_energy)


class NumericTests(unittest.TestCase):
    def compare(self, observed, reference, **kwargs):
        options = dict(observed_source="measurement", reference_source="independent",
                       atol=0.0, rtol=0.0)
        options.update(kwargs)
        result = compare_numeric(observed, reference, **options)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        return result

    def test_verdicts_and_evidence(self):
        for a, b, status in [([1.0], [1.0], "pass"), ([2.0], [1.0], "fail"),
                             (None, [1.0], "unverified"), ([1.0], None, "unverified"),
                             ([None], [1.0], "unverified"), ([], [], "unexercised"),
                             (np.empty((0, 3)), np.empty((0, 3)), "unexercised")]:
            with self.subTest(status=status, a=a):
                result = self.compare(a, b)
                self.assertEqual(result["status"], status)
                if status in ("unverified", "unexercised"):
                    self.assertIsNone(result["evidence"]["max_abs"])
                    self.assertIsNone(result["evidence"]["max_rel"])
                    self.assertIsNone(result["evidence"]["mismatch_count"])
        evidence = self.compare(np.array([2], dtype=np.float32), [1.0])["evidence"]
        self.assertEqual((evidence["count"], evidence["observed_shape"],
                          evidence["observed_dtype"], evidence["max_abs"],
                          evidence["max_rel"], evidence["mismatch_count"]),
                         (1, [1], "float32", 1.0, 1.0, 1))

    def test_tolerance_convention_and_precision(self):
        self.assertEqual(self.compare([1.75], [1.0], atol=.5, rtol=.25)["status"], "pass")
        self.assertEqual(self.compare([2.0], [1.0], rtol=.5)["status"], "fail")
        self.assertEqual(self.compare([1.0], [2.0], rtol=.5)["status"], "pass")
        self.assertEqual(self.compare([1 + 1e-12], [1.0])["status"], "fail")
        self.assertEqual(self.compare([2**63 + 1], [2**63])["evidence"]["max_abs"], 1.0)
        self.assertEqual(self.compare([2**63 + 1], [float(2**63)])["status"], "fail")
        self.assertEqual(self.compare([0.0], [-0.0])["evidence"]["max_rel"], 0.0)
        evidence = self.compare([1.0], [0.0], atol=1.0)["evidence"]
        self.assertIsNone(evidence["max_rel"])
        self.assertTrue(evidence["max_rel_nonfinite"])
        self.assertEqual(self.compare([np.finfo(float).max], [-np.finfo(float).max])["status"], "fail")

    def test_unverified_provenance_and_aliasing(self):
        for label in (None, "", "  ", 1, "independent", " independent "):
            self.assertEqual(self.compare([1], [1], observed_source=label)["status"], "unverified")
        a = np.arange(6.0)
        for b in (a, a.view(), a[::-1], a.reshape(2, 3)):
            self.assertEqual(self.compare(a, b)["status"], "unverified")
        same = [1.0]
        self.assertEqual(self.compare(same, same)["status"], "unverified")
        self.assertEqual(self.compare(a, a.copy())["status"], "pass")
        self.assertEqual(self.compare(np.ma.array([1], mask=[True]), [1])["status"], "unverified")

    def test_invalid_tolerances_and_data(self):
        for name in ("atol", "rtol"):
            for bad in (-1, np.nan, np.inf, -np.inf, True, "1", None, [1], 1j):
                with self.subTest(name=name, bad=bad), self.assertRaises(ValueError):
                    self.compare([1], [1], **{name: bad})
        for bad in ([np.nan], [np.inf], [-np.inf], [True], ["1"], [1j],
                    [{}], [[1], [2, 3]], [[1]], [1, 2], np.empty((0, 3))):
            with self.subTest(bad=bad):
                self.assertEqual(self.compare(bad, [1.0])["status"], "fail")
                self.assertEqual(self.compare([1.0], bad)["status"], "fail")


class IndependentCalculationTests(unittest.TestCase):
    def test_kinetic_energy_direct_sum_and_precision(self):
        result = independent_kinetic_energy([[1, 2, 2], [0, 3, 4], [2, 0, 0]],
                                           [2, 4, 3], [1, 0, 1], np.int64(3))
        np.testing.assert_array_equal(result, [50, 15, 0])
        self.assertEqual(result.dtype, np.float64)
        v = np.array([[1.0001, 2, 3]], dtype=np.float32)
        expected = .5 * sum(float(x)**2 for x in v[0])
        self.assertEqual(independent_kinetic_energy(v, [1], [0], 1)[0], expected)
        np.testing.assert_array_equal(independent_kinetic_energy(
            np.empty((0, 3)), [], np.array([], dtype=int), 2), [0, 0])

    def test_kinetic_energy_invalid_inputs(self):
        good = dict(velocities=[[1, 2, 3]], masses=[1], graph_indices=[0], num_graphs=1)
        cases = {"velocities": ([1, 2, 3], [[1, 2]], [[np.nan, 0, 0]], [[1e308, 0, 0]], [[True]*3]),
                 "masses": ([0], [-1], [np.inf], [[1]], [], ["1"], [1j]),
                 "graph_indices": ([-1], [1], [2**64-1], [0.5], [0.0], [True], [[0]], [], [np.nan]),
                 "num_graphs": (0, -1, 1.5, 1.0, True, [1], np.inf, 2**64-1)}
        for key, values in cases.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    independent_kinetic_energy(**dict(good, **{key: value}))

    def test_drift_metrics_and_first_reference(self):
        np.testing.assert_allclose(independent_energy_drift([14, 8], [10, 10], [2, 4], 2), [1, .25])
        np.testing.assert_array_equal(independent_energy_drift([14, 8], [10, 10], 2, [0, 1]), [2, 1])
        np.testing.assert_array_equal(independent_energy_drift([14, 8], [10, 10], 2, 99, "absolute"), [4, 2])
        self.assertEqual(independent_energy_drift(10.000000000001, 10.0, 1, 0), abs(10.000000000001 - 10))
        self.assertIsNone(independent_energy_drift([1.0], None, 1, 0))
        self.assertIsNone(independent_energy_drift(1.0, None, 1, 0, "absolute"))
        self.assertGreater(independent_energy_drift(2.0, 1.0, np.int64(2**62), 8), 0)

    def test_drift_invalid_inputs_even_without_reference(self):
        good = dict(total=[1.0], reference=[1.0], num_atoms=1, step_count=0)
        cases = {"total": (None, [[1]], [np.nan], ["1"], [True]),
                 "reference": (1.0, [[1]], [1, 2], [np.inf], [1j]),
                 "num_atoms": (0, -1, 1.1, 1.0, True, [1, 2], [[1]]),
                 "step_count": (-1, .5, 1.0, True, [0, 1], [[0]], np.nan),
                 "metric": ("relative", None)}
        for key, values in cases.items():
            for value in values:
                for reference in ([1.0], None) if key != "reference" else ([1.0],):
                    with self.subTest(key=key, value=value, reference=reference), self.assertRaises(ValueError):
                        independent_energy_drift(**{**good, "reference": reference, key: value})
        with self.assertRaises(ValueError):
            independent_energy_drift(1e308, -1e308, 1, 1)


class HookTests(unittest.TestCase):
    def setUp(self):
        self.expected = [(0, "before", "clamp"), (0, "after", "drift"), (1, "before", "clamp")]
        self.events = []
        for invocation, (counter, stage, hook) in enumerate(self.expected):
            for kind in ("entry", "return"):
                self.events.append(dict(sequence=len(self.events), event=kind,
                                        invocation_id=invocation, step_counter=counter,
                                        stage=stage, hook_type=hook))

    def audit(self, events, status, expected=None):
        result = audit_hook_events(events, self.expected if expected is None else expected)
        self.assertEqual(result["status"], status, result)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        return result["evidence"]

    def test_actual_order_and_counts(self):
        evidence = self.audit(self.events, "pass")
        self.assertEqual([evidence[k] for k in ("event_count", "entry_count", "return_count", "pair_count")], [6, 3, 3, 3])
        self.assertEqual(evidence["by_hook"]["clamp"], dict(entry=2, **{"return": 2}, pairs=2))
        self.assertEqual(evidence["actual_entries"], [list(e) for e in self.expected])
        self.audit(self.events, "fail", self.expected[::-1])
        swapped = self.events[2:4] + self.events[:2] + self.events[4:]
        swapped = [dict(event, sequence=i) for i, event in enumerate(swapped)]
        self.audit(swapped, "fail")  # Same counts and valid pairs, wrong full order.
        self.audit(None, "unverified")
        self.audit([], "unverified", [])

    def test_missing_duplicate_and_unpaired_events(self):
        for index in range(len(self.events)):
            self.audit(self.events[:index] + self.events[index+1:], "fail")
        for index in (0, 1):
            duplicate = self.events[:index+1] + [self.events[index]] + self.events[index+1:]
            self.audit([dict(e, sequence=i) for i, e in enumerate(duplicate)], "fail")
        self.audit(self.events[:4], "fail")  # A whole invocation missing.
        self.audit([self.events[1], self.events[0]] + self.events[2:], "fail")

    def test_bad_schema_sequence_and_pair_metadata(self):
        for key, value in [("sequence", 0), ("sequence", -1), ("sequence", 1.5),
                           ("sequence", True), ("step_counter", 1), ("stage", "other"),
                           ("hook_type", "other"), ("instance_id", "wrong-instance"),
                           ("invocation_id", "unknown"), ("invocation_id", []),
                           ("event", "call"), ("stage", " ")]:
            with self.subTest(key=key, value=value):
                events = copy.deepcopy(self.events)
                events[1][key] = value
                self.audit(events, "fail")
        for key in self.events[0]:
            events = copy.deepcopy(self.events)
            del events[0][key]
            self.audit(events, "fail")
        self.audit([None], "fail")
        self.audit({"calls": 3}, "fail")
        for bad in (None, [()], [(0.0, "before", "clamp")], [(0, "", "clamp")]):
            with self.assertRaises(ValueError):
                audit_hook_events(self.events, bad)

    def test_nested_calls_and_sequence_gaps(self):
        nested = [self.events[i] for i in (0, 2, 3, 1, 4, 5)]
        nested = [dict(event, sequence=i*3, invocation_id=str(event["invocation_id"]))
                  for i, event in enumerate(nested)]
        self.audit(nested, "pass")


if __name__ == "__main__":
    unittest.main()