import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run


def clean():
    return {"scenario": "review_signoff", "required_gates": ["drc"],
            "envelopes": [{"id": "synthetic-fixture", "gate": "drc",
                           "status": "completed", "validation": {"verdict": "pass"},
                           "violations": 0}],
            "fixture_notice": "SYNTHETIC TEST ONLY; not chip signoff"}


class ContractTests(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ.get("DESIGN_REVIEW_TEST_ROOT",
                                   str(Path.cwd() / "design-review-test-evidence"))).resolve()
        if os.name == "nt" and not str(root).startswith("\\\\?\\"):
            root = Path("\\\\?\\" + str(root))
        self.root = root / (self._testMethodName + "-" + uuid.uuid4().hex)
        self.input = self.root / "input"
        self.input.mkdir(parents=True)
        self.output = self.root / "output"
        self.workdir = self.root / "workdir"

    def check(self, params, verdict="pass", code=0, status="completed", raw=None,
              params_path=None):
        path = self.input / "params.json"
        path.write_text(raw if raw is not None else json.dumps(params), encoding="utf-8")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            actual_code = run.execute(params_path or path, self.input, self.output, self.workdir)
        cde = json.loads((self.output / "common_design_envelope.json").read_text())
        self.assertEqual((actual_code, cde["status"], cde["validation"]["verdict"]),
                         (code, status, verdict))
        for key in run.utils._CDE_REQUIRED_FIELDS:
            self.assertIn(key, cde)
        for artifact in cde["artifacts"].values():
            self.assertFalse(Path(artifact).is_absolute())
            self.assertTrue((self.output / artifact).is_file(), artifact)
        lines = [v[len("CDE_JSON="):] for v in stdout.getvalue().splitlines()
                 if v.startswith("CDE_JSON=")]
        self.assertEqual(len(lines), int(bool(code)))
        if lines:
            self.assertEqual(json.loads(lines[0]), cde)
        return cde

    def test_positive_inline_fixture(self):
        cde = self.check(clean())
        self.assertEqual(cde["validation"]["confidence"], "low")

    def test_positive_hashed_fixture(self):
        p = clean()
        env = p["envelopes"][0]
        env["signoff_evidence"] = {"drc_report": "fixture.txt"}
        (self.input / "fixture.txt").write_text("SYNTHETIC ONLY", encoding="utf-8")
        path = self.input / "fixture.json"
        path.write_text(json.dumps(env), encoding="utf-8")
        p["envelopes"] = [str(path)]
        p["require_artifacts"] = True
        cde = self.check(p)
        self.assertTrue(cde["signoff_evidence"]["evidence_verified"])
        self.assertEqual(cde["validation"]["confidence"], "high")
        for item in cde["signoff_evidence"]["evidence_audit"]["artifacts"]:
            self.assertTrue((self.output / item["path"]).is_file())

    def native_drc(self, report="drc_klayout.log"):
        """Native producer dialect, still clearly labelled synthetic test data."""
        env = {"tool": "drc", "status": "completed", "objective": "synthetic DRC",
               "progress": {"stage_key": "drc", "gate_closed": True},
               "validation": {"verdict": "pass"},
               "results": {"unwaived_violations": {"value": 0, "unit": "count"}},
               "signoff_evidence": {"per_engine": {"klayout": {
                   "report": report, "deck_variables": {
                       "deck_variables": {"input": True, "report": True},
                       "deck_variables_missing": []}}}},
               "provenance": {"report": [report]}}
        path = self.input / "native.json"
        path.write_text(json.dumps(env), encoding="utf-8")
        return {"scenario": "review_signoff", "required_gates": ["DRC"],
                "envelopes": [str(path)], "require_artifacts": True}

    def test_native_drc_nested_and_list_report_opened_without_mutation(self):
        p = self.native_drc()
        logs = self.input / "logs"
        logs.mkdir()
        report = b"SYNTHETIC NATIVE-SHAPED DRC REPORT ONLY\n"
        (logs / "drc_klayout.log").write_bytes(report)
        source_before = (self.input / "native.json").read_bytes()
        cde = self.check(p)
        self.assertEqual((self.input / "native.json").read_bytes(), source_before)
        self.assertEqual(cde["signoff_evidence"]["covered_gates"], {"drc": "native.json"})
        self.assertTrue(cde["signoff_evidence"]["evidence_verified"])
        self.assertEqual(cde["signoff_evidence"]["artifacts_opened"], 1)
        audit = cde["signoff_evidence"]["evidence_audit"]["artifacts"][0]
        self.assertEqual((self.output / audit["path"]).read_bytes(), report)
        self.assertEqual(audit["sha256"]["sha256"], run.hashlib.sha256(report).hexdigest())

    def test_native_drc_missing_nested_report_is_unverified(self):
        cde = self.check(self.native_drc(), "pass_with_caveats")
        self.assertFalse(cde["signoff_evidence"]["evidence_verified"])
        self.assertEqual(cde["signoff_evidence"]["artifacts_opened"], 0)

    def test_native_drc_ambiguous_basename_is_unverified(self):
        p = self.native_drc()
        for folder in ("logs", "results"):
            (self.input / folder).mkdir()
            (self.input / folder / "drc_klayout.log").write_text("SYNTHETIC " + folder)
        cde = self.check(p, "pass_with_caveats")
        self.assertFalse(cde["signoff_evidence"]["evidence_verified"])
        reason = cde["signoff_evidence"]["missing_artifacts"][0]["reason"]
        self.assertIn("ambiguous", reason)

    def test_nested_and_list_path_escape_rejected(self):
        for field in ("signoff_evidence", "provenance"):
            with self.subTest(field=field):
                env = {field: {"nested": {"report": [str(self.root / "outside.log")]}}}
                with self.assertRaisesRegex(ValueError, "escapes immutable"):
                    run.validate(dict(clean(), envelopes=[dict(env, id="escape")]), self.input)

    def test_nested_relative_traversal_rejected(self):
        p = self.native_drc("../outside.log")
        self.check(p, "fail", 1, "failed")

    def test_known_native_gate_does_not_accept_conflicting_or_unknown_producer(self):
        unknown = {"tool": "invented", "progress": {"stage_key": "drc"}}
        conflicting = {"tool": "lvs", "progress": {"stage_key": "drc"}}
        self.assertIsNone(run.utils.envelope_gate(unknown))
        self.assertIsNone(run.utils.envelope_gate(conflicting))
        self.assertIsNone(run.utils.envelope_gate({"progress": {"stage_key": "drc"}}))
        p = clean()
        p["envelopes"][0].pop("gate")
        p["envelopes"][0].update(unknown)
        self.check(p, "fail", 1)

    def test_explicit_legacy_gate_is_preserved(self):
        self.assertEqual(run.utils.envelope_gate({"gate": "DRC", "tool": "custom"}), "drc")

    def test_native_gate_coverage_shared_by_evidence_scenario(self):
        p = clean()
        p.update(scenario="check_evidence", required_gates=["DRC"])
        p["envelopes"][0].pop("gate")
        p["envelopes"][0].update(tool="drc", progress={"stage_key": "drc"})
        self.check(p)

    def test_native_gate_waiver_matching(self):
        p = clean()
        p.update(scenario="adjudicate_waivers", waivers=[{
            "gate": "DRC", "owner": "fixture", "justification": "synthetic only",
            "rule_deck_version": "fixture"}])
        p["envelopes"][0].pop("gate")
        p["envelopes"][0].update(tool="drc", violations=1)
        self.check(p)

    def test_artifact_traversal_is_bounded_and_not_arbitrary_text(self):
        env = {"provenance": {"note": "not-a-file", "report": ["one.log", "two.log"]}}
        self.assertEqual([v for _, v in run.utils.artifact_citations(env)], ["one.log", "two.log"])
        node = {"report": "one.log"}
        for _ in range(14):
            node = {"nested": node}
        with self.assertRaisesRegex(ValueError, "exceeds review limits"):
            list(run.utils.artifact_citations({"provenance": node}))

    def test_deck_metadata_exemption_does_not_hide_string_path_escape(self):
        env = {"id": "SYNTHETIC-ESCAPE", "signoff_evidence": {
            "per_engine": {"klayout": {"deck_variables": {"report": "../outside.log"}}}}}
        self.assertEqual([v for _, v in run.utils.artifact_citations(env)], ["../outside.log"])
        with self.assertRaisesRegex(ValueError, "escapes immutable"):
            run.validate(dict(clean(), envelopes=[env], evidence_root=str(self.input)), self.input)

    def test_boolean_report_outside_typed_deck_metadata_is_invalid(self):
        for section in ({"report": True}, {"deck_variables": {"report": True, "input": "bad"}}):
            with self.subTest(section=section), self.assertRaisesRegex(ValueError, "must be a string"):
                list(run.utils.artifact_citations({"signoff_evidence": section}))

    def test_missing_gate(self):
        p = clean(); p["required_gates"].append("lvs")
        self.check(p, "fail", 1)

    def test_unwaived_self_reported_pass(self):
        p = clean(); p["envelopes"][0]["violations"] = 1
        self.check(p, "fail", 1)

    def test_invalid_waiver_does_not_clear(self):
        p = clean(); p["envelopes"][0]["violations"] = 1
        p["waivers"] = [{"id": "invalid", "gate": "drc"}]
        self.check(p, "fail", 1)

    def test_valid_waiver(self):
        p = clean(); p["envelopes"][0]["violations"] = 1
        p["waivers"] = [{"id": "synthetic-waiver", "gate": "drc", "owner": "fixture",
                         "justification": "synthetic only", "rule_deck_version": "fixture"}]
        self.check(p)

    def test_invalid_waiver_caveat(self):
        p = clean(); p["waivers"] = [{}]
        self.check(p, "pass_with_caveats")

    def test_unreadable_count(self):
        p = clean(); del p["envelopes"][0]["violations"]
        self.check(p, "not_assessable", 1)

    def test_boolean_negative_string_or_fractional_count_is_not_measured_zero(self):
        for value in (False, True, -1, "0", 0.5):
            with self.subTest(value=value):
                env = {"results": {"unwaived_violations": {"value": value},
                                   "drc_violations": {"value": 0}}}
                self.assertIsNone(run.utils._env_violations(env))
        p = clean(); p["envelopes"][0]["violations"] = False
        self.check(p, "not_assessable", 1)

    def test_missing_upstream_verdict_cannot_close_review(self):
        p = clean(); p["envelopes"][0]["validation"] = {}
        self.check(p, "not_assessable", 1)

    def test_review_upstream_verdict_cannot_close_review(self):
        p = clean(); p["envelopes"][0]["validation"]["verdict"] = "review"
        self.check(p, "not_assessable", 1)

    def test_upstream_status_must_be_completed(self):
        p = clean(); p["envelopes"][0]["status"] = "running"
        self.check(p, "not_assessable", 1)

    def test_upstream_caveats_are_not_laundered_into_clean_pass(self):
        p = clean(); p["envelopes"][0]["validation"]["verdict"] = "pass_with_caveats"
        self.check(p, "pass_with_caveats")

    def test_boolean_budgeted_measurement_is_unmeasured(self):
        p = clean(); p["budget"] = {"area": {"max": 10}}
        p["envelopes"][0]["qor_metrics"] = {"area": False}
        self.check(p, "pass_with_caveats")

    def test_no_required_list_floor_missing(self):
        p = clean(); del p["required_gates"]
        self.check(p, "fail", 1)

    def test_floor_met_completeness_unknown(self):
        p = clean(); p["required_gates"] = []
        p["envelopes"] += [{"id": g, "gate": g, "violations": 0} for g in ("lvs", "antenna")]
        self.check(p, "not_assessable", 1)

    def test_budget_unmeasured(self):
        p = clean(); p["budget"] = {"area": {"max": 10}}
        self.check(p, "pass_with_caveats")

    def test_budget_exceeded(self):
        p = clean(); p["budget"] = {"area": {"max": 10}}
        p["envelopes"][0]["qor_metrics"] = {"area": {"value": 11}}
        self.check(p, "fail", 1)

    def test_policy_override(self):
        p = clean(); p["envelopes"][0]["signoff_evidence"] = {"pdk_policy_override": True}
        self.check(p, "pass_with_caveats")

    def test_missing_cited_artifact(self):
        p = clean(); p["evidence_root"] = str(self.input)
        p["envelopes"][0]["signoff_evidence"] = {"drc_report": "absent.txt"}
        self.check(p, "pass_with_caveats")

    def test_waiver_adjudication_pass(self):
        p = clean(); p["scenario"] = "adjudicate_waivers"; p["waivers"] = []
        self.check(p)

    def test_waiver_adjudication_unreadable(self):
        p = clean(); p["scenario"] = "adjudicate_waivers"; p["waivers"] = []
        del p["envelopes"][0]["violations"]
        self.check(p, "not_assessable", 1)

    def test_evidence_pass(self):
        p = clean(); p["scenario"] = "check_evidence"
        self.check(p)

    def test_evidence_missing_field(self):
        p = clean(); p["scenario"] = "check_evidence"
        del p["envelopes"][0]["validation"]
        self.check(p, "fail", 1)

    def test_apostrophe_unicode(self):
        p = clean(); p["fixture_notice"] = "designer's fixture \u03bc"
        self.check(p)

    def test_fresh_output_required(self):
        self.output.mkdir(); (self.output / "old.txt").write_text("stale")
        self.check(clean(), "fail", 1, "failed")

    def test_fresh_workdir_required(self):
        self.workdir.mkdir(); (self.workdir / "old.txt").write_text("stale")
        self.check(clean(), "fail", 1, "failed")

    def test_params_path_escape(self):
        self.check(clean(), "fail", 1, "failed", params_path=self.root / "outside.json")

    def test_cited_path_escape(self):
        p = clean(); p["envelopes"][0]["signoff_evidence"] = {"log": str(self.root / "outside")}
        self.check(p, "fail", 1, "failed")

    def test_envelope_path_escape(self):
        p = clean(); p["envelopes"] = [str(self.root / "outside.json")]
        self.check(p, "fail", 1, "failed")


def add_invalid_case(name, raw):
    def test(self):
        self.check(None, "fail", 1, "failed", raw=raw)
    setattr(ContractTests, "test_invalid_" + name, test)


for name, raw in {
    "malformed_json": "{",
    "array": "[]",
    "duplicate_key": '{"scenario":"review_signoff","scenario":"check_evidence"}',
    "nonfinite": '{"scenario":"review_signoff","budget":{"area":{"max":NaN}}}',
    "missing_scenario": '{"envelopes":[]}',
    "aliased_scenario": '{"mode":"review_signoff","envelopes":[]}',
    "unsupported_scenario": '{"scenario":"invented","envelopes":[]}',
    "object_string": json.dumps(dict(clean(), budget="{}")),
    "empty_envelopes": json.dumps(dict(clean(), envelopes=[])),
    "waivers_object": json.dumps(dict(clean(), waivers={})),
    "gates_string": json.dumps(dict(clean(), required_gates="drc")),
    "budget_boolean": json.dumps(dict(clean(), budget={"area": {"max": True}})),
    "require_artifacts_string": json.dumps(dict(clean(), require_artifacts="true")),
}.items():
    add_invalid_case(name, raw)


if __name__ == "__main__":
    unittest.main()
