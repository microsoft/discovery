"""Offline regressions for the Python validator embedded in the public runner."""

import ast
from contextlib import redirect_stdout
import io
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests


RUNNER = Path(__file__).resolve().parents[1] / "skills" / "discovery-services-agent-deployer" / "scripts" / "deploy-discovery-agent.ps1"
SOURCE = RUNNER.read_text(encoding="utf-8").split("$ValidatePy = Join-Path", 1)[1].split("@'\n", 1)[1].split("\n'@ | Set-Content $ValidatePy", 1)[0]


def message(text):
    return {"type": "message", "content": [{"type": "output_text", "text": text}]}


def response(output, status="completed", response_id="response-1"):
    return {"id": response_id, "status": status, "output": output}


def execution(actual=2.1, expected=2.1, size=123, name="rstatistics-ExecuterCode"):
    receipt = {
        "checks": [{"name": "slope", "actual": actual, "expected": expected, "tolerance": 1e-8}],
        "artifacts": [{"path": "/output/results.csv", "bytes": size}],
    }
    return [
        {"type": "function_call", "name": name, "call_id": "run"},
        {"type": "function_call_output", "call_id": "run", "output":
         "Tool execution succeeded.\nNew resources: discovery://resources/outputs/output/\n"
         "DISCOVERY_VALIDATION_RESULT=" + json.dumps(receipt)},
        message("Completed."),
    ]


class RegistrySubstitutionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_registry_replacement_preserves_action_inputs(self):
        source = RUNNER.read_text(encoding="utf-8")
        block = source.split('$AcrLoginServer =', 1)[1].split('\n\npython -c', 1)[0]
        block = '$AcrLoginServer =' + block
        original = (
            'qualified: "{name}.azurecr.io/tool:1.1.1"\n'
            'bare: "{name}/tool:1.1.1"\n'
            'name: "{{#if name}}{{name}}{{/if}}"\n'
            'expression: "{{name}}.azurecr.io/{{name}}/output"\n'
        )
        expected = original.replace(
            '"{name}.azurecr.io/', '"testregistry.azurecr.io/'
        ).replace('"{name}/', '"testregistry.azurecr.io/')
        with tempfile.TemporaryDirectory() as directory:
            tool = Path(directory) / "tool.yaml"
            tool.write_text(original, encoding="utf-8")
            script = (
                "$ErrorActionPreference = 'Stop'\n"
                "$Config = @{ acrName = 'testregistry' }\n"
                "$Ctx = @{ tempToolYaml = $env:TEST_TOOL_YAML }\n"
                + block + "\n" + block
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                env={**os.environ, "TEST_TOOL_YAML": str(tool)},
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(tool.read_text(encoding="utf-8-sig"), expected)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({
            "workspaceEndpoint": "https://workspace.example",
            "apiVersion": "2026-06-01",
            "project": "test",
            "tokenCommand": "test-token",
        }), encoding="utf-8")
        self.tool = self.root / "tool.yaml"
        self.tool.write_text("code_environments:\n  - language: r\n", encoding="utf-8")
        self.result = self.root / "validation-result.json"

    def run_validator(self, bodies, *, tool=True, continuation=False, retries=1):
        bodies = iter(bodies)
        calls = []
        current = None
        conversations = itertools.count(1)

        def request(method, url, **kwargs):
            nonlocal current
            calls.append((method, url, kwargs))
            if method == "POST" and url.endswith("/responses"):
                current = next(bodies)
                data = current
            elif method == "GET":
                if current is None:
                    current = next(bodies)
                data = current
            elif method == "POST" and "/conversations?" in url:
                data = {"name": f"conversation-{next(conversations)}"}
            else:
                data = {}
            result = Mock()
            result.json.return_value = data
            result.status_code = 200
            return result

        args = ["validation_test.py", str(self.config), "RStatisticsAgent",
                "Check slope 2.1 and write results.", "true", str(self.result),
                "rstatistics" if tool else "", str(self.tool) if tool else "",
                str(continuation).lower()]
        clock = itertools.count(1793000000, 10)
        log = io.StringIO()
        error = None
        with patch.object(sys, "argv", args), patch.dict(os.environ, {
            "VALIDATION_WAIT_SECONDS": "1", "VALIDATION_MAX_RETRIES": str(retries),
        }), patch("requests.request", side_effect=request), patch("subprocess.run", return_value=Mock(stdout="test-token")), \
             patch("time.sleep"), patch("time.time", side_effect=lambda: next(clock)), \
             patch("atexit.register"), patch("signal.signal"), redirect_stdout(log):
            try:
                exec(compile(SOURCE, str(RUNNER), "exec"), {"__name__": "__main__"})
            except (SystemExit, RuntimeError, InterruptedError, requests.RequestException) as caught:
                error = caught
        return json.loads(self.result.read_text()), calls, log.getvalue(), error

    def test_embedded_script_compiles(self):
        ast.parse(SOURCE)

    def test_real_execution_and_receipt_pass(self):
        result, _, _, error = self.run_validator([response(execution())])
        self.assertIsNone(error)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["responseId"], "response-1")
        self.assertTrue((self.root / "validation-response-response-1.json").exists())

    def test_text_or_assistant_only_receipt_never_passes(self):
        for text in ("OK", "VALIDATION_R_OK", "DISCOVERY_VALIDATION_RESULT=" + json.dumps({"checks": []})):
            with self.subTest(text=text):
                result, _, _, _ = self.run_validator([response([message(text)])])
                self.assertEqual(result["status"], "failed")

    def test_wrong_tool_and_unmatched_call_fail(self):
        for output in (execution(name="other-ExecuterCode"), execution()[1:]):
            with self.subTest(output=output):
                result, _, _, _ = self.run_validator([response(output)])
                self.assertEqual(result["status"], "failed")

    def test_bad_numeric_checks_and_empty_artifacts_fail(self):
        for actual, size in ((2.0, 123), (float("nan"), 123), (float("inf"), 123), (2.1, 0)):
            with self.subTest(actual=actual, size=size):
                result, _, _, _ = self.run_validator([response(execution(actual=actual, size=size))])
                self.assertEqual(result["status"], "failed")

    def test_tool_failure_cannot_be_overridden_by_assistant(self):
        output = execution()
        output[1]["output"] = "Tool execution failed. ContainerExitCode 1"
        output[-1] = message("Success!")
        result, _, _, _ = self.run_validator([response(output)])
        self.assertEqual(result["status"], "failed")

    def test_success_word_cannot_mask_tool_error(self):
        output = execution()
        output[1]["output"] = {"status": "completed", "error": {"code": "ToolRunError"}}
        result, _, _, _ = self.run_validator([response(output)])
        self.assertEqual(result["status"], "failed")

    def test_missing_receipt_and_missing_output_resource_fail(self):
        for text in (
            "Tool execution succeeded.",
            execution()[1]["output"].replace("discovery://resources/outputs/output/", ""),
        ):
            with self.subTest(text=text):
                output = execution()
                output[1]["output"] = text
                result, _, _, _ = self.run_validator([response(output)])
                self.assertEqual(result["status"], "failed")

    def test_native_action_does_not_require_code_receipt(self):
        self.tool.write_text("actions: []\n", encoding="utf-8")
        output = execution()
        output[1]["output"] = "Tool execution succeeded."
        result, _, _, error = self.run_validator([response(output)])
        self.assertIsNone(error)
        self.assertEqual(result["status"], "passed")

    def test_api_required_action_pauses(self):
        body = response([], "requires_action")
        body["required_action"] = {"type": "submit_tool_outputs"}
        result, _, _, error = self.run_validator([body])
        self.assertEqual(error.code, 3)
        self.assertEqual(result["status"], "input_required")
        self.assertEqual(result["requiredAction"], body["required_action"])

    def test_discovery_platform_confirmation_pauses(self):
        body = response([], "in_progress")
        confirmation = {"name": "approval-1", "status": "AwaitingUserInput", "toolName": "rstatistics"}
        body["discoveryProperties"] = {"confirmations": [confirmation]}
        result, _, _, error = self.run_validator([body])
        self.assertEqual(error.code, 3)
        self.assertEqual(result["status"], "input_required")
        self.assertEqual(result["requiredAction"]["confirmations"], [confirmation])

    def test_approved_discovery_confirmation_does_not_block(self):
        body = response(execution())
        body["discoveryProperties"] = {"confirmations": [{"status": "Approved"}]}
        result, _, _, error = self.run_validator([body])
        self.assertIsNone(error)
        self.assertEqual(result["status"], "passed")

    def test_earlier_failure_can_recover_with_verified_execution(self):
        output = [
            {"type": "function_call", "name": "rstatistics-ExecuterCode", "call_id": "old"},
            {"type": "function_call_output", "call_id": "old", "output": "Tool execution failed."},
        ] + execution()
        result, _, _, error = self.run_validator([response(output)])
        self.assertIsNone(error)
        self.assertEqual(result["status"], "passed")

    def test_confirmation_pauses_without_deleting(self):
        result, calls, log, error = self.run_validator([response([message("Please confirm I should proceed.")])])
        self.assertEqual(result["status"], "input_required")
        self.assertEqual(error.code, 3)
        self.assertIn("VALIDATION_APPROVAL_INPUT_REQUIRED=true", log)
        self.assertFalse(any(method == "DELETE" for method, _, _ in calls))

    def test_explicit_approval_request_pauses_and_reuses_conversation(self):
        result, calls, _, error = self.run_validator([
            response([message("Proposed plan for approval.\nPlease approve and I'll execute this plan.")])
        ])
        self.assertEqual(result["status"], "input_required")
        self.assertEqual(error.code, 3)
        self.assertFalse(any(method == "DELETE" for method, _, _ in calls))
        result, calls, _, error = self.run_validator([response(execution())], continuation=True)
        self.assertIsNone(error)
        self.assertEqual(result["conversation"], "conversation-1")
        posts = [url for method, url, _ in calls if method == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertIn("/conversations/conversation-1/", posts[0])

    def test_pending_get_user_input_pauses_and_resumes_same_response(self):
        pending = response([{"type": "function_call", "name": "GetUserInput", "call_id": "approval"}], "in_progress")
        result, _, _, _ = self.run_validator([pending])
        self.assertEqual(result["status"], "input_required")
        result, calls, _, error = self.run_validator([response(execution())])
        self.assertIsNone(error)
        self.assertEqual(result["status"], "passed")
        self.assertFalse(any(method == "POST" for method, _, _ in calls))

    def test_confirmation_continuation_reuses_conversation(self):
        self.run_validator([response([message("Please confirm I should proceed.")])])
        result, calls, _, error = self.run_validator([response(execution())], continuation=True)
        self.assertIsNone(error)
        self.assertEqual(result["conversation"], "conversation-1")
        post = [(url, kwargs) for method, url, kwargs in calls if method == "POST"]
        self.assertEqual(len(post), 1)
        self.assertIn("/conversations/conversation-1/", post[0][0])
        self.assertIn("User continuation:", post[0][1]["json"]["input"][0]["content"][0]["text"])

    def test_confirmation_is_not_automatically_approved(self):
        body = response([message("Please confirm I should proceed.")])
        self.run_validator([body])
        result, calls, _, error = self.run_validator([body])
        self.assertEqual(error.code, 3)
        self.assertEqual(result["status"], "input_required")
        self.assertFalse(any(method == "POST" for method, _, _ in calls))

    def test_timeout_retains_identifiers_and_investigation(self):
        result, calls, _, error = self.run_validator([response([], "in_progress", "timed-out")])
        self.assertEqual(error.code, 2)
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["responseId"], "timed-out")
        self.assertTrue(result["conversation"])
        self.assertFalse(any(method == "DELETE" for method, _, _ in calls))

    def test_incomplete_response_is_terminal(self):
        result, _, _, _ = self.run_validator([response([], "incomplete")])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["responseStatus"], "incomplete")

    def test_timeout_retry_preserves_original_prompt_and_evidence(self):
        result, calls, _, error = self.run_validator([
            response([], "in_progress", "timed-out"),
            response(execution(), response_id="retry"),
        ], retries=2)
        self.assertIsNone(error)
        self.assertEqual(result["status"], "passed")
        prompts = [kw["json"]["input"][0]["content"][0]["text"]
                   for method, url, kw in calls if method == "POST" and url.endswith("/responses")]
        self.assertEqual(prompts[0], prompts[1])
        self.assertNotIn("Reply with exactly OK", prompts[1])
        self.assertTrue((self.root / "validation-response-timed-out.json").exists())

    def test_no_tool_agent_still_works(self):
        result, _, _, error = self.run_validator([response([message("I summarize documents.")])], tool=False)
        self.assertIsNone(error)
        self.assertEqual(result["status"], "passed")


if __name__ == "__main__":
    unittest.main()
