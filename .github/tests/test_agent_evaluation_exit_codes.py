"""Offline regression tests for the agent-evaluation pipeline's exit policies.

The actual CLI, capture/conversion, aggregation and reporting code runs. Only
authentication, agent invocation and the Foundry evaluation boundary are mocked.
No Azure credentials, evaluation dependencies or network calls are needed.
"""

from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


EVALUATORS = (
    Path(__file__).resolve().parents[2] / "utilities" / "agent-evaluation" / "evaluators"
)


class PipelineExitTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(TemporaryDirectory()))
        self.dataset_dir = self.root / "datasets"
        self.dataset_dir.mkdir()
        self.output_dir = self.root / "output"
        self.fail_queries = set()
        self.error_message = "HTTP 503: controlled invocation failure"
        self.scenario = "all_pass"
        self.invocations = []
        self.eval_rows = []
        self.closed = False

        packages = {}
        for name in (
            "azure", "azure.ai", "azure.ai.projects", "azure.identity",
            "openai", "openai.types", "openai.types.eval_create_params", "aiohttp",
        ):
            module = ModuleType(name)
            module.__path__ = []
            packages[name] = module
            if "." in name:
                parent, attribute = name.rsplit(".", 1)
                setattr(packages[parent], attribute, module)
        packages["azure.ai.projects"].AIProjectClient = lambda **kwargs: object()
        packages["azure.identity"].DefaultAzureCredential = object
        packages["openai.types.eval_create_params"].DataSourceConfigCustom = dict
        packages["aiohttp"].ClientSession = object
        packages["aiohttp"].ClientError = ConnectionError
        stack.enter_context(patch.dict(sys.modules, packages))
        stack.enter_context(patch.object(sys, "path", list(sys.path)))
        for name in (
            "azure_credential", "discovery_client", "eval_datasets",
            "responses_to_eval_dataset", "run_offline_eval",
        ):
            sys.modules.pop(name, None)
        spec = importlib.util.spec_from_file_location(
            "_test_agent_evaluation_pipeline", EVALUATORS / "pipeline.py"
        )
        assert spec is not None and spec.loader is not None
        self.pipeline = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.pipeline
        spec.loader.exec_module(self.pipeline)
        self.offline = sys.modules["run_offline_eval"]
        self.pipeline.get_credential = object
        case = self

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                case.closed = True

            async def create_investigation(self, *args, **kwargs):
                return "offline-investigation"

            async def invoke(self, project, investigation, agent, query, **kwargs):
                case.invocations.append(query)
                if query in case.fail_queries:
                    raise SystemExit(case.error_message)
                return {
                    "status": "completed",
                    "output": [{
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Fixture answer."}],
                    }],
                }, f"conversation-{query}"

        self.pipeline.DiscoveryAgentClient = FakeClient
        self.pipeline.execute_eval = self.execute_eval

    def execute_eval(self, project, name, rows, criteria, timeout):
        self.eval_rows.extend(rows)
        items = []
        for index, row in enumerate(rows):
            self.assertEqual(row["response"][0]["role"], "assistant")
            if self.scenario == "evaluator_item_error" and index == 0:
                items.append({
                    "id": str(index), "status": "error",
                    "error": "Controlled evaluator error", "results": [],
                })
                continue
            passed = not (self.scenario == "criterion_failure" and index == 0)
            items.append({
                "id": str(index),
                "results": [{"name": "coherence", "passed": passed,
                             "score": 5 if passed else 1}],
            })
        summary, errored, errors = self.offline._aggregate(items)
        run = SimpleNamespace(id="run-fixture", eval_id="eval-fixture", status="completed")
        return run, summary, errored, errors

    def run_cli(self, mode, *, rows=None, max_queries=0):
        if rows is None:
            rows = [{"query": "query-1"}, {"query": "query-2"}]
        (self.dataset_dir / "probe-evaluators.json").write_text(
            json.dumps({"evaluators": ["builtin.coherence"], "data": rows}),
            encoding="utf-8",
        )
        args = [
            "pipeline.py",
            "--workspace-api-url", "https://discovery.invalid",
            "--discovery-project", "offline-project",
            "--agent", "offline-agent",
            "--foundry-project-endpoint", "https://foundry.invalid",
            "--dataset-dir", str(self.dataset_dir),
            "--suites", "probe",
            "--output-dir", str(self.output_dir),
            "--fail-on", mode,
            "--max-queries", str(max_queries),
            "--concurrency", "2",
        ]
        output = io.StringIO()
        with patch.object(sys, "argv", args), redirect_stdout(output):
            code = self.pipeline.main()
        self.console = output.getvalue()
        self.assertTrue(self.closed)
        summary = json.loads((self.output_dir / "summary.json").read_text())
        self.assertEqual(summary["exit_code"], code)
        return code, summary["suites"]["probe"]

    def check_case(self, scenario, mode, expected):
        self.scenario = scenario
        if scenario == "all_capture_failures":
            self.fail_queries = {"query-1", "query-2"}
        elif scenario == "partial_capture_failure":
            self.fail_queries = {"query-1"}
        code, suite = self.run_cli(mode)
        self.assertEqual(code, expected, self.console)
        self.assertEqual(self.invocations, ["query-1", "query-2"])
        self.assertEqual(suite["capture_errors"], len(self.fail_queries))
        self.assertEqual(suite["captured"], 2 - len(self.fail_queries))
        self.assertEqual(len(self.eval_rows), suite["captured"])
        self.assertEqual(suite["errored"], int(scenario == "evaluator_item_error"))
        markdown = (self.output_dir / "summary.md").read_text(encoding="utf-8")
        self.assertIn(f"Capture errors: {len(self.fail_queries)}", markdown)
        if scenario == "all_capture_failures":
            self.assertEqual(suite["status"], "no-captures")
            self.assertIsNone(suite["results"])
        else:
            self.assertEqual(suite["status"], "completed")
            result = json.loads(Path(suite["results"]).read_text())
            self.assertEqual(result["errored"], suite["errored"])

    def test_all_capture_failures_errored(self):
        self.check_case("all_capture_failures", "errored", 2)

    def test_all_capture_failures_failed(self):
        self.check_case("all_capture_failures", "failed", 2)

    def test_all_capture_failures_none(self):
        self.check_case("all_capture_failures", "none", 0)

    def test_partial_capture_failure_errored(self):
        self.check_case("partial_capture_failure", "errored", 2)

    def test_partial_capture_failure_failed(self):
        self.check_case("partial_capture_failure", "failed", 2)

    def test_partial_capture_failure_none(self):
        self.check_case("partial_capture_failure", "none", 0)

    def test_all_pass_errored(self):
        self.check_case("all_pass", "errored", 0)

    def test_all_pass_failed(self):
        self.check_case("all_pass", "failed", 0)

    def test_all_pass_none(self):
        self.check_case("all_pass", "none", 0)

    def test_criterion_failure_errored(self):
        self.check_case("criterion_failure", "errored", 0)

    def test_criterion_failure_failed(self):
        self.check_case("criterion_failure", "failed", 2)

    def test_criterion_failure_none(self):
        self.check_case("criterion_failure", "none", 0)

    def test_evaluator_item_error_errored(self):
        self.check_case("evaluator_item_error", "errored", 2)

    def test_evaluator_item_error_failed(self):
        self.check_case("evaluator_item_error", "failed", 2)

    def test_evaluator_item_error_none(self):
        self.check_case("evaluator_item_error", "none", 0)

    def test_query_limit_does_not_count_unattempted_failures(self):
        self.fail_queries = {"query-2"}
        code, suite = self.run_cli("failed", max_queries=1)
        self.assertEqual(code, 0, self.console)
        self.assertEqual(self.invocations, ["query-1"])
        self.assertEqual(suite["captured"], 1)
        self.assertEqual(suite["capture_errors"], 0)

    def test_queryless_row_remains_a_skip(self):
        code, suite = self.run_cli("errored", rows=[{}, {"query": "query-1"}])
        self.assertEqual(code, 0, self.console)
        self.assertEqual(self.invocations, ["query-1"])
        self.assertEqual(suite["captured"], 1)
        self.assertEqual(suite["capture_errors"], 0)

    def test_capture_and_evaluation_errors_are_separate(self):
        self.fail_queries = {"query-2"}
        self.scenario = "evaluator_item_error"
        code, suite = self.run_cli("errored")
        self.assertEqual(code, 2, self.console)
        self.assertEqual(suite["capture_errors"], 1)
        self.assertEqual(suite["errored"], 1)
        self.assertEqual(suite["captured"], 1)

    def test_capture_timeout_is_counted(self):
        self.fail_queries = {"query-1"}
        self.error_message = "Timed out waiting for response"
        code, suite = self.run_cli("errored")
        self.assertEqual(code, 2, self.console)
        self.assertEqual(suite["capture_errors"], 1)
        self.assertEqual(suite["captured"], 1)
        self.assertIn(self.error_message, self.console)

    def offline_report_code(self, status, fail_on):
        run = SimpleNamespace(id="run-fixture", eval_id="eval-fixture", status=status)
        with redirect_stdout(io.StringIO()):
            return self.offline.report(run, {}, 0, [], None, fail_on)

    def test_offline_incomplete_run_fails_under_errored(self):
        self.assertEqual(self.offline_report_code("failed", "errored"), 2)
        self.assertEqual(self.offline_report_code("canceled", "errored"), 2)

    def test_offline_incomplete_run_fails_under_failed(self):
        self.assertEqual(self.offline_report_code("failed", "failed"), 2)

    def test_offline_incomplete_run_respects_fail_on_none(self):
        self.assertEqual(self.offline_report_code("failed", "none"), 0)

    def test_offline_completed_run_passes_clean_results(self):
        self.assertEqual(self.offline_report_code("completed", "errored"), 0)


if __name__ == "__main__":
    unittest.main()
