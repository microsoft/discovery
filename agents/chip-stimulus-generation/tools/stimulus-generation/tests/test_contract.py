"""Stdlib contract and domain regression, retaining evidence in an explicit root."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import random
import sys
import unittest
from unittest import mock
import uuid

TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))
import run
import stimulus_generation_utils as utils

configured = os.environ.get("CHIP_VALIDATION_EVIDENCE_ROOT")
if not configured or not Path(configured).is_absolute():
    raise RuntimeError("Set CHIP_VALIDATION_EVIDENCE_ROOT to an absolute writable evidence root")
EVIDENCE = Path(configured)
POSITIVE = {"scenario": "constrained_random", "dut_top": "alu",
            "constraints": {"a": {"min": 0, "max": 15},
                            "op": {"values": ["add", "sub"], "weights": [3, 1]}},
            "count": 8, "seeds": [1729]}
SHORTFALL = {"scenario": "constrained_random", "dut_top": "alu",
             "constraints": {"a": {"min": 0, "max": 1000000}},
             "constraint_blocks": [{"then": {"a": 0}}],
             "count": 8, "seeds": [1729], "max_rejection_tries": 0}


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.root = EVIDENCE / uuid.uuid4().hex[:12]
        self.root.mkdir(parents=True, exist_ok=False)
        (self.root / "case.txt").write_text(self.id(), encoding="utf-8")
        self.input, self.output, self.work = [self.root / n for n in ("input", "output", "workdir")]
        for path in (self.input, self.output, self.work):
            path.mkdir()
        for name, value in (("INPUT_DIR", self.input), ("OUTPUT_DIR", self.output),
                            ("WORK_DIR", self.work)):
            patcher = mock.patch.object(run, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, path, text):
        path.write_text(text, encoding="utf-8")
        return path

    def execute(self, params=None, args=None):
        if args is None:
            self.write(self.input / "params.json", json.dumps(params, ensure_ascii=False))
            args = ["--params-file", str(self.input / "params.json")]
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.input.rglob("*") if p.is_file()}
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                code = run.main(args)
        self.write(self.root / "stdout.log", stdout.getvalue())
        self.write(self.root / "stderr.log", stderr.getvalue())
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in self.input.rglob("*") if p.is_file()})
        path = self.output / "common_design_envelope.json"
        env = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if code == 1:
            lines = [line[9:] for line in stdout.getvalue().splitlines() if line.startswith("CDE_JSON=")]
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0]), env)
        else:
            self.assertNotIn("CDE_JSON=", stdout.getvalue())
        return code, env

    def failure(self, params=None, args=None):
        code, env = self.execute(params, args)
        self.assertEqual(code, 1)
        self.assertEqual((env["status"], env["validation"]["verdict"]), ("failed", "fail"))
        self.assertTrue(env["error"])
        self.assertEqual(env["tools_used"], [{"name": "stimulus-generation", "version": "1.2.0"}])

    def stimulus(self, env):
        ref = env["signoff_evidence"]["file"]
        self.assertEqual(ref, "results/stimulus.json")
        return json.loads((self.output / ref).read_text())

    def test_seeded_positive_exact_legacy_sequence(self):
        code, env = self.execute(POSITIVE)
        self.assertEqual((code, env["status"], env["validation"]["verdict"]), (0, "completed", "pass"))
        rng = random.Random(1729)
        expected = [{"seed": 1729, "stimulus": {"a": rng.randint(0, 15),
                     "op": rng.choices(["add", "sub"], weights=[3, 1])[0]}} for _ in range(8)]
        self.assertEqual(self.stimulus(env), expected)
        self.assertEqual(env["signoff_evidence"]["constraints_solvable"], True)

    def test_shortfall_unknown_not_unsatisfiable(self):
        code, env = self.execute(SHORTFALL)
        self.assertEqual((code, env["status"], env["validation"]["verdict"]), (1, "failed", "fail"))
        self.assertEqual(env["results"]["stimulus_shortfall"]["value"], 8)
        self.assertIsNone(env["signoff_evidence"]["constraints_solvable"])
        self.assertEqual(self.stimulus(env), [])

    def test_rejection_sampling_conformance(self):
        params = copy.deepcopy(POSITIVE)
        params["constraint_blocks"] = [{"if": {"op": "add"}, "then": {"a": {"min": 8}}}]
        params["max_rejection_tries"] = 100
        code, env = self.execute(params)
        self.assertEqual(code, 0)
        constraints = utils._normalize_constraints(params["constraints"])
        blocks = utils._normalize_blocks(params["constraint_blocks"])
        self.assertTrue(all(not utils._txn_violations(t["stimulus"], constraints, blocks)
                            for t in self.stimulus(env)))

    def test_static_contradiction(self):
        params = copy.deepcopy(POSITIVE)
        params["constraint_blocks"] = [{"then": {"a": 999}}]
        self.failure(params)

    def test_domain_post_mutation_recheck(self):
        with mock.patch.object(utils, "_sample", return_value={"a": 999, "op": "add"}):
            code, env = self.execute(POSITIVE)
        self.assertEqual(code, 1)
        self.assertEqual(self.stimulus(env), [])
        self.assertEqual(env["results"]["stimulus_shortfall"]["value"], 8)

    def test_soft_constraint_outside_domain(self):
        params = copy.deepcopy(POSITIVE)
        params["soft_constraints"] = {"a": {"value": 999, "probability": 1}}
        self.failure(params)

    def test_randc_and_soft_preserve_controls(self):
        params = {"scenario": "constrained_random", "dut_top": "dut",
                  "constraints": {"a": [0, 1, 2, 3], "b": {"min": 0, "max": 3}},
                  "randc_fields": ["a"], "soft_constraints": {"b": {"value": 3, "probability": 1}},
                  "seeds": [1729], "count": 4}
        code, env = self.execute(params)
        txns = self.stimulus(env)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(t["stimulus"]["a"] for t in txns), [0, 1, 2, 3])
        self.assertTrue(all(t["stimulus"]["b"] == 3 for t in txns))

    def test_weighted_distribution(self):
        params = {"scenario": "constrained_random", "dut_top": "dut",
                  "constraints": {"op": ["add", "sub"]},
                  "value_distributions": {"op": {"add": 1, "sub": 0}}, "count": 4, "seeds": [1]}
        code, env = self.execute(params)
        self.assertEqual(code, 0)
        self.assertTrue(all(t["stimulus"]["op"] == "add" for t in self.stimulus(env)))

    def test_coverage_directed_actual_values(self):
        params = copy.deepcopy(POSITIVE)
        params.update(scenario="coverage_directed", holes=[{"field": "a", "value": 15, "count": 2}])
        code, env = self.execute(params)
        txns = [t for t in self.stimulus(env) if "directed_at" in t]
        self.assertEqual(code, 0)
        self.assertEqual(len(txns), 2)
        self.assertTrue(all(t["stimulus"]["a"] == 15 for t in txns))

    def test_directed_caveat_exact_text(self):
        text = "counter's “latency” isn’t &#39;rewritten&#39;"
        code, env = self.execute({"scenario": "directed", "tests": [{"name": text}]})
        self.assertEqual((code, env["validation"]["verdict"]), (0, "pass_with_caveats"))
        self.assertEqual(self.stimulus(env), [{"name": text}])

    def test_directed_mapped_pass(self):
        code, env = self.execute({"scenario": "directed", "tests": [{"vplan_item": "VP-1"}]})
        self.assertEqual((code, env["validation"]["verdict"]), (0, "pass"))

    def test_vplan_immutable_hash(self):
        path = self.write(self.input / "vplan.json", '{"items":[{"id":"VP-1"}]}')
        params = copy.deepcopy(POSITIVE)
        params["vplan_file"] = str(path)
        code, env = self.execute(params)
        self.assertEqual(code, 0)
        self.assertEqual(env["vplan"], str(path))
        self.assertEqual(env["provenance"]["input_hashes"]["vplan.json"]["sha256"],
                         hashlib.sha256(path.read_bytes()).hexdigest())

    def test_explicit_file_no_fallback(self):
        self.write(self.input / "bad.json", '{"scenario":')
        self.write(self.input / "params.json", json.dumps(POSITIVE))
        self.failure(args=["--params-file", str(self.input / "bad.json")])

    def test_explicit_argv_no_fallback(self):
        self.write(self.input / "params.json", json.dumps(POSITIVE))
        self.failure(args=['{"scenario":'])

    def test_missing_file(self):
        self.failure(args=[])

    def test_path_escape(self):
        outside = self.write(self.root / "params.json", json.dumps(POSITIVE))
        self.failure(args=["--params-file", str(outside)])

    def test_relative_path(self):
        self.failure(args=["--params-file", "params.json"])

    def test_symlink_resolution_escape(self):
        with mock.patch.object(Path, "resolve", autospec=True,
                               side_effect=lambda p: self.root if p.name == "link.json" else p):
            self.failure(args=["--params-file", str(self.input / "link.json")])

    def test_nonobject(self):
        self.failure(args=["[]"])

    def test_alias_no_scenario(self):
        self.failure({"mode": "directed", "tests": [{"name": "test"}]})

    def test_unknown_scenario(self):
        self.failure({"scenario": "SMT"})

    def test_nonfinite(self):
        self.failure(args=['{"scenario":"directed","tests":[{"a":NaN}]}'])

    def test_bad_count(self):
        params = copy.deepcopy(POSITIVE)
        params["count"] = 0
        self.failure(params)

    def test_bad_budget(self):
        params = copy.deepcopy(POSITIVE)
        params["max_rejection_tries"] = -1
        self.failure(params)

    def test_empty_seeds(self):
        params = copy.deepcopy(POSITIVE)
        params["seeds"] = []
        self.failure(params)

    def test_invalid_seed(self):
        params = copy.deepcopy(POSITIVE)
        params["seeds"] = [True]
        self.failure(params)

    def test_invalid_constraint_object(self):
        params = copy.deepcopy(POSITIVE)
        params["constraints"] = '{"a":[1]}'
        self.failure(params)

    def test_empty_domain(self):
        params = copy.deepcopy(POSITIVE)
        params["constraints"] = {"a": {"values": []}}
        self.failure(params)

    def test_typo_domain(self):
        params = copy.deepcopy(POSITIVE)
        params["constraints"] = {"a": {"minimum": 0, "maximum": 1}}
        self.failure(params)

    def test_noninteger_range(self):
        params = copy.deepcopy(POSITIVE)
        params["constraints"] = {"a": {"min": "0", "max": 1}}
        self.failure(params)

    def test_invalid_weight(self):
        params = copy.deepcopy(POSITIVE)
        params["constraints"]["op"]["weights"] = [-1, 2]
        self.failure(params)

    def test_empty_block(self):
        params = copy.deepcopy(POSITIVE)
        params["constraint_blocks"] = [{}]
        self.failure(params)

    def test_unknown_block_field(self):
        params = copy.deepcopy(POSITIVE)
        params["constraint_blocks"] = [{"then": {"typo": 0}}]
        self.failure(params)

    def test_invalid_directed_tests(self):
        self.failure({"scenario": "directed", "tests": ["not an object"]})

    def test_nonempty_output_refused(self):
        sentinel = self.write(self.output / "common_design_envelope.json", '{"historical":true}')
        code, env = self.execute(POSITIVE)
        self.assertEqual((code, env), (2, {"historical": True}))
        self.assertEqual(sentinel.read_text(), '{"historical":true}')
        self.assertEqual(list(self.work.iterdir()), [])

    def test_nonempty_workdir_refused(self):
        sentinel = self.write(self.work / "sentinel.txt", "original")
        code, env = self.execute(POSITIVE)
        self.assertEqual((code, env), (2, None))
        self.assertEqual(sentinel.read_text(), "original")

    def test_environment_cannot_redirect(self):
        outside = self.root / "outside"
        with mock.patch.dict(os.environ, {k: str(outside) for k in
                             ("CHIP_OUTPUT_DIR", "OUTPUT_DIR", "CHIP_WORK_DIR", "WORK_DIR")}):
            code, env = self.execute(POSITIVE)
        self.assertEqual(code, 0)
        self.assertFalse(outside.exists())
        self.stimulus(env)

    def test_completed_fail_exits_nonzero(self):
        with mock.patch.object(utils, "dispatch", return_value={
                "tool": "stimulus-generation", "status": "completed",
                "results": {}, "validation": {"verdict": "fail"}}):
            code, env = self.execute(POSITIVE)
        self.assertEqual((code, env["status"]), (1, "completed"))

    def test_review_not_promoted(self):
        with mock.patch.object(utils, "dispatch", return_value={
                "tool": "stimulus-generation", "status": "completed",
                "results": {}, "validation": {"verdict": "review"}}):
            code, env = self.execute(POSITIVE)
        self.assertEqual((code, env["validation"]["verdict"]), (0, "review"))

    def test_missing_cde_fails(self):
        self.assertEqual(run._authoritative_exit_code(), 1)

    def test_corrupt_cde_fails(self):
        self.write(self.output / "common_design_envelope.json", "{")
        self.assertEqual(run._authoritative_exit_code(), 1)


if __name__ == "__main__":
    unittest.main()
