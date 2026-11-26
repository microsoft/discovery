"""Native stdlib regression; all operation artifacts are retained in the campaign."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock
import uuid

TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))
import run
import req_identity

def evidence_root():
    configured = os.environ.get("CHIP_VALIDATION_EVIDENCE_ROOT")
    if configured:
        root = Path(configured)
        if not root.is_absolute():
            raise RuntimeError("CHIP_VALIDATION_EVIDENCE_ROOT must be an absolute writable path")
        return root
    if (TOOL_DIR.name == "design-intent"
            and TOOL_DIR.parent.name == "tools"
            and TOOL_DIR.parent.parent.name == "chip-design-intent"
            and TOOL_DIR.parent.parent.parent.name == "agents-docker"):
        return (TOOL_DIR.parent.parent.parent.parent / "sessions" /
                "e7299a797e921fba775271076d229622df69ea71abe05774963223dece9cfc8c" /
                "chip-agent-validation" / "outputs" / "design-intent-package")
    raise RuntimeError("Set CHIP_VALIDATION_EVIDENCE_ROOT to an absolute writable "
                       "mount (for example /evidence) when testing outside the source package")


EVIDENCE = evidence_root()


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.root = EVIDENCE / uuid.uuid4().hex[:16]
        self.root.mkdir(parents=True, exist_ok=False)
        with (self.root / "case.txt").open("x", encoding="utf-8") as stream:
            stream.write(self.id())
        self.input = self.root / "input"
        self.output = self.root / "output"
        self.work = self.root / "workdir"
        for directory in (self.input, self.output, self.work):
            directory.mkdir()
        for name, value in (("INPUT_DIR", self.input), ("OUTPUT_DIR", self.output),
                            ("WORK_DIR", self.work)):
            patcher = mock.patch.object(run, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, path, value):
        with path.open("x", encoding="utf-8") as stream:
            stream.write(value)
        return path

    def execute(self, params=None, args=None):
        if args is None:
            self.write(self.input / "params.json", json.dumps(params, ensure_ascii=False))
            args = ["--params-file", str(self.input / "params.json")]
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.input.iterdir() if p.is_file()}
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                code = run.main(args)
        self.write(self.root / "stdout.log", stdout.getvalue())
        self.write(self.root / "stderr.log", stderr.getvalue())
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.input.iterdir() if p.is_file()}
        self.assertEqual(before, after)
        envelope = self.output / "common_design_envelope.json"
        return code, json.loads(envelope.read_text(encoding="utf-8")) if envelope.exists() else None

    def assert_failure(self, params=None, args=None):
        code, envelope = self.execute(params, args)
        self.assertEqual(code, 1)
        self.assertEqual(envelope["status"], "failed")
        self.assertEqual(envelope["validation"]["verdict"], "fail")
        self.assertTrue(envelope["error"])
        self.assertEqual(envelope["tools_used"],
                         [{"name": "design-intent", "version": "1.2.0"}])

    def test_malformed_explicit_file_does_not_fallback(self):
        self.write(self.input / "bad.json", '{"scenario":')
        self.write(self.input / "params.json", '{"scenario":"normalize","requirements":["< 5 ns"]}')
        self.assert_failure(args=["--params-file", str(self.input / "bad.json")])

    def test_malformed_argv_does_not_fallback(self):
        self.write(self.input / "params.json", '{"scenario":"normalize","requirements":["< 5 ns"]}')
        self.assert_failure(args=['{"scenario":'])

    def test_missing_scenario(self):
        self.assert_failure({"mode": "normalize", "requirements": ["< 5 ns"]})

    def test_unknown_scenario(self):
        self.assert_failure({"scenario": "requirements", "requirements": ["< 5 ns"]})

    def test_nonobject_params(self):
        self.assert_failure(args=["[]"])

    def test_missing_parameter_file(self):
        self.assert_failure(args=[])

    def test_apostrophe_and_unicode_exact_preservation(self):
        text = "The counter's “latency” isn’t &#39;rewritten&#39; and shall be < 5 ns"
        code, env = self.execute({"scenario": "normalize",
                                 "requirements": [{"id": "DR-1", "text": text}]})
        self.assertEqual((code, env["validation"]["verdict"]), (0, "pass"))
        spec = json.loads((self.output / env["signoff_evidence"]["specification"]).read_text())
        self.assertEqual(spec["requirements"][0]["text"], text)
        self.assertEqual(env["provenance"]["specification"], "results/specification.json")
        self.assertTrue((self.output / "reports" / "REPORT.md").is_file())

    def test_parameter_file_escape(self):
        outside = self.write(self.root / "params.json", '{"scenario":"normalize"}')
        self.assert_failure(args=["--params-file", str(self.input / ".." / outside.name)])

    def test_symlink_escape_resolution(self):
        # Mock only the OS resolution result: Windows symlink creation may require elevation.
        with mock.patch.object(Path, "resolve", autospec=True,
                               side_effect=lambda path: self.root if path.name == "link.json" else path):
            self.assert_failure(args=["--params-file", str(self.input / "link.json")])

    def test_explicit_null_requirements_cannot_use_alias(self):
        self.assert_failure({"scenario": "normalize", "requirements": None, "reqs": ["< 5 ns"]})

    def test_explicit_null_reserve(self):
        self.assert_failure({"scenario": "ppa_budget", "targets": {"area_um2": 100},
                             "blocks": ["core"], "integration_reserve_pct": None})

    def test_malformed_inline_object(self):
        self.assert_failure({"scenario": "ppa_budget", "targets": '{"area_um2":100}',
                             "blocks": ["core"]})

    def test_nonfinite_json(self):
        self.assert_failure(args=['{"scenario":"ppa_budget","targets":{"area_um2":NaN},"blocks":["core"]}'])

    def test_nonfinite_weight(self):
        self.assert_failure({"scenario": "ppa_budget", "targets": {"area_um2": 100},
                             "blocks": [{"name": "core", "weight": "nan"}]})

    def test_nonempty_output_refused_without_overwrite(self):
        sentinel = self.write(self.output / "common_design_envelope.json", '{"historical":true}')
        code, _ = self.execute({"scenario": "normalize", "requirements": ["< 5 ns"]})
        self.assertEqual(code, 2)
        self.assertEqual(sentinel.read_text(), '{"historical":true}')
        self.assertEqual(list(self.work.iterdir()), [])
        self.assertNotIn("CDE_JSON=", (self.root / "stdout.log").read_text(encoding="utf-8"))

    def test_nonempty_workdir_refused(self):
        sentinel = self.write(self.work / "existing.txt", "original")
        code, env = self.execute({"scenario": "normalize", "requirements": ["< 5 ns"]})
        self.assertEqual((code, env), (2, None))
        self.assertEqual(sentinel.read_text(), "original")
        self.assertEqual(list(self.output.iterdir()), [])

    def test_empty_requirements_failure(self):
        self.assert_failure({"scenario": "normalize", "requirements": []})

    def test_unit_bearing_ppa_budget(self):
        code, env = self.execute({"scenario": "ppa_budget",
                                 "targets": {"area_um2": "12 mm2", "power_mw": "0.05 W",
                                             "freq_mhz": "1.2 GHz"},
                                 "blocks": [{"name": "core", "weight": 3},
                                            {"name": "cache", "weight": 2}],
                                 "integration_reserve_pct": 10})
        self.assertEqual((code, env["validation"]["verdict"]), (0, "pass"))
        evidence = env["signoff_evidence"]
        self.assertEqual(env["tools_used"],
                         [{"name": "design-intent", "version": "1.2.0"}])
        self.assertTrue(evidence["closes"])
        self.assertEqual(evidence["targets_parsed"]["area_um2"]["value"], 12000000)
        self.assertEqual(evidence["targets_parsed"]["freq_mhz"]["value"], 1200)
        self.assertEqual(evidence["integration_reserve"]["area_um2"], 1200000)
        self.assertTrue((self.output / evidence["budget"]).is_file())
        self.assertEqual(env["provenance"]["budget"], "results/ppa_budget.json")

    def test_missing_reserve_preserves_review(self):
        code, env = self.execute({"scenario": "ppa_budget", "targets": {"area_um2": 100},
                                 "blocks": ["core"]})
        self.assertEqual((code, env["validation"]["verdict"]), (0, "review"))
        self.assertFalse(env["qor_metrics"]["integration_reserve_declared"])

    def test_wrong_dimension_all_targets_failed(self):
        self.assert_failure({"scenario": "ppa_budget", "targets": {"area_um2": "5 ns"},
                             "blocks": ["core"]})

    def test_wrong_dimension_partial_targets_completed_fail(self):
        code, env = self.execute({"scenario": "ppa_budget",
                                 "targets": {"area_um2": "5 ns", "power_mw": "50 mW"},
                                 "blocks": ["core"], "integration_reserve_pct": 0})
        self.assertEqual((code, env["status"], env["validation"]["verdict"]),
                         (1, "completed", "fail"))

    def test_negative_weight_keeps_domain_defect(self):
        code, env = self.execute({"scenario": "ppa_budget", "targets": {"area_um2": 100},
                                 "blocks": [{"name": "core", "weight": -1},
                                            {"name": "cache", "weight": 2}]})
        self.assertEqual((code, env["validation"]["verdict"]), (1, "fail"))
        self.assertTrue(env["signoff_evidence"]["weight_findings"])

    def test_derived_ids_caveats_and_nonpositional_identity(self):
        requirements = ["Latency < 5 ns", "Power < 50 mW"]
        code, env = self.execute({"scenario": "normalize", "requirements": requirements})
        self.assertEqual((code, env["validation"]["verdict"]), (0, "pass_with_caveats"))
        first, _ = req_identity.assign(requirements)
        reverse, _ = req_identity.assign(list(reversed(requirements)))
        self.assertEqual([r["id"] for r in first], list(reversed([r["id"] for r in reverse])))

    def test_duplicate_id_not_renamed(self):
        code, env = self.execute({"scenario": "normalize",
                                 "requirements": [{"id": "DR-1", "text": "Latency < 5 ns"},
                                                  {"id": "DR-1", "text": "Power < 50 mW"}]})
        self.assertEqual((code, env["status"], env["validation"]["verdict"]),
                         (1, "completed", "fail"))
        spec = json.loads((self.output / "results" / "specification.json").read_text())
        self.assertEqual([r["id"] for r in spec["requirements"]], ["DR-1", "DR-1"])

    def test_malformed_id_zero_is_not_derived(self):
        code, env = self.execute({"scenario": "normalize",
                                 "requirements": [{"id": 0, "text": "Latency < 5 ns"}]})
        self.assertEqual((code, env["validation"]["verdict"]), (1, "fail"))
        self.assertEqual(env["signoff_evidence"]["identity"]["derived"], 0)

    def test_duplicate_text_distinct_ids_keeps_caveats(self):
        code, env = self.execute({"scenario": "normalize",
                                 "requirements": [{"id": "DR-1", "text": "Latency < 5 ns"},
                                                  {"id": "DR-2", "text": "Latency < 5 ns"}]})
        self.assertEqual((code, env["validation"]["verdict"]), (0, "pass_with_caveats"))
        self.assertEqual(env["qor_metrics"]["duplicates"], 1)

    def test_environment_cannot_redirect_outputs(self):
        with mock.patch.dict(os.environ, {"CHIP_OUTPUT_DIR": str(self.root / "escape"),
                                         "CHIP_WORK_DIR": str(self.root / "escape")}):
            self.assert_failure({"scenario": "normalize"})
        self.assertFalse((self.root / "escape").exists())

    def test_actual_process_failure_exit(self):
        params = self.write(self.input / "params.json", '{"scenario":"unknown"}')
        script = ("import sys; from pathlib import Path; "
                  f"sys.path.insert(0, {str(TOOL_DIR)!r}); import run; "
                  f"run.INPUT_DIR=Path({str(self.input)!r}); "
                  f"run.OUTPUT_DIR=Path({str(self.output)!r}); "
                  f"run.WORK_DIR=Path({str(self.work)!r}); "
                  f"sys.exit(run.main(['--params-file', {str(params)!r}]))")
        result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True,
                                text=True, check=False)
        self.write(self.root / "stdout.log", result.stdout)
        self.write(self.root / "stderr.log", result.stderr)
        self.assertEqual(result.returncode, 1)
        env = json.loads((self.output / "common_design_envelope.json").read_text())
        self.assertEqual(env["validation"]["verdict"], "fail")

    def test_missing_envelope_never_success(self):
        self.assertEqual(run._authoritative_exit_code(), 1)

    def test_packaged_evidence_uses_explicit_environment(self):
        with mock.patch.dict(os.environ, {"CHIP_VALIDATION_EVIDENCE_ROOT": str(self.root)}):
            with mock.patch.dict(evidence_root.__globals__, {"TOOL_DIR": Path("/app")}):
                self.assertEqual(evidence_root(), self.root)

    def test_packaged_evidence_without_environment_has_clear_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.dict(evidence_root.__globals__, {"TOOL_DIR": Path("/app")}):
                with self.assertRaisesRegex(RuntimeError, "Set CHIP_VALIDATION_EVIDENCE_ROOT"):
                    evidence_root()

    def test_evidence_environment_rejects_relative_path(self):
        with mock.patch.dict(os.environ, {"CHIP_VALIDATION_EVIDENCE_ROOT": "relative"}):
            with self.assertRaisesRegex(RuntimeError, "absolute writable path"):
                evidence_root()

    def logged_envelope(self):
        lines = (self.root / "stdout.log").read_text(encoding="utf-8").splitlines()
        marked = [line.removeprefix("CDE_JSON=") for line in lines
                  if line.startswith("CDE_JSON=")]
        self.assertEqual(len(marked), 1)
        return json.loads(marked[0])

    def test_completed_fail_log_matches_exact_persisted_envelope(self):
        code, env = self.execute({"scenario": "ppa_budget",
                                 "targets": {"area_um2": "5 ns", "power_mw": "50 mW"},
                                 "blocks": ["core"], "integration_reserve_pct": 10})
        logged = self.logged_envelope()
        self.assertEqual(code, 1)
        self.assertEqual(logged, env)
        self.assertEqual(logged["status"], "completed")
        self.assertEqual(logged["validation"]["verdict"], "fail")
        self.assertTrue(logged["validation"]["note"])

    def test_parameter_error_log_preserves_json_and_trace(self):
        self.assert_failure(args=['{"scenario":"counter\'s\\n“bad”"}'])
        logged = self.logged_envelope()
        persisted = json.loads((self.output / "common_design_envelope.json").read_text(
            encoding="utf-8"))
        self.assertEqual(logged, persisted)
        self.assertEqual(logged["validation"]["note"], logged["error"])
        self.assertIn("ValueError", logged["traceback"])

    def test_domain_error_log_preserves_error(self):
        self.assert_failure({"scenario": "ppa_budget", "targets": {"area_um2": "5 ns"},
                             "blocks": ["core"]})
        logged = self.logged_envelope()
        persisted = json.loads((self.output / "common_design_envelope.json").read_text(
            encoding="utf-8"))
        self.assertEqual(logged, persisted)
        self.assertTrue(logged["error"])

    def test_success_does_not_emit_failure_cde_log(self):
        code, _ = self.execute({"scenario": "ppa_budget", "targets": {"area_um2": 100},
                               "blocks": ["core"], "integration_reserve_pct": 10})
        self.assertEqual(code, 0)
        self.assertNotIn("CDE_JSON=", (self.root / "stdout.log").read_text(encoding="utf-8"))

    def test_cde_closed_before_report_and_preserved_on_report_exception(self):
        observed = []

        def report_failure(results):
            with (self.output / "common_design_envelope.json").open(
                    encoding="utf-8") as stream:
                persisted = json.load(stream)
            observed.append(persisted["validation"]["verdict"])
            self.assertEqual(persisted["objective"], results["objective"])
            raise RuntimeError("injected narrative report failure")

        with mock.patch.object(run.utils, "_write_report_md", side_effect=report_failure):
            code, env = self.execute({"scenario": "ppa_budget",
                                     "targets": {"area_um2": "12 mm2"},
                                     "blocks": ["core"], "integration_reserve_pct": 10})
        self.assertEqual(observed, ["pass"])
        self.assertEqual((code, env["status"], env["validation"]["verdict"]),
                         (0, "completed", "pass"))
        self.assertTrue((self.output / env["signoff_evidence"]["budget"]).is_file())
        self.assertIn("injected narrative report failure",
                      (self.root / "stdout.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
