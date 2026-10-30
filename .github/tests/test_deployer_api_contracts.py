"""Offline API-version and knowledge-base binding regressions for both deployers."""

import ast
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

import yaml


SKILLS = Path(__file__).resolve().parents[1] / "skills"
AGENT = SKILLS / "discovery-services-agent-deployer"
STARTER = SKILLS / "discovery-services-starter-kit-deployer"
AGENT_SOURCE = (AGENT / "scripts" / "deploy-discovery-agent.ps1").read_text(encoding="utf-8")
STARTER_SOURCE = (STARTER / "scripts" / "deploy-discovery-starter-kit.ps1").read_text(encoding="utf-8")
GA_ID = "/bookshelves/library/knowledgeBases/reference"
PREVIEW_ID = GA_ID + "/versions/1"


class ApiDefaultsTests(unittest.TestCase):
    def test_both_templates_default_to_ga(self):
        for skill in (AGENT, STARTER):
            with self.subTest(skill=skill.name):
                template = json.loads((skill / "config.template.json").read_text(encoding="utf-8"))
                self.assertEqual(template["apiVersion"], "2026-06-01")

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_agent_default_and_explicit_preview_override(self):
        assignment = next(line for line in AGENT_SOURCE.splitlines() if "$ApiVersion = Resolve-ConfigField" in line)
        script = """
function Resolve-ConfigField {
  param($ConfigObj, $Field, $Default, $PromptLabel)
  if ($ConfigObj.ContainsKey($Field)) { return $ConfigObj[$Field] }
  return $Default
}
$WorkingConfig = @{}
""" + assignment + """
if ($ApiVersion -ne '2026-06-01') { throw "Unexpected default: $ApiVersion" }
$WorkingConfig = @{ apiVersion = '2026-02-01-preview' }
""" + assignment + """
if ($ApiVersion -ne '2026-02-01-preview') { throw "Override was replaced: $ApiVersion" }
"""
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_starter_default_and_explicit_preview_override(self):
        functions = "function Test-ConfigValuePresent" + STARTER_SOURCE.split(
            "function Test-ConfigValuePresent", 1,
        )[1].split("function Write-BuildModeInputRequest", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "config.json"
            fallback = Path(directory) / "agent-config.json"
            for agent_override, starter_override, expected in (
                ({}, {}, "2026-06-01"),
                ({"apiVersion": "2026-02-01-preview"}, {}, "2026-02-01-preview"),
                ({"apiVersion": "2026-06-01"}, {"apiVersion": "2026-02-01-preview"}, "2026-02-01-preview"),
            ):
                with self.subTest(agent=agent_override, starter=starter_override):
                    local.write_text(json.dumps(starter_override), encoding="utf-8")
                    fallback.write_text(json.dumps(agent_override), encoding="utf-8")
                    script = """
$ErrorActionPreference = 'Stop'
function Get-ConfigPath { $env:TEST_LOCAL }
function Get-AgentDeployerConfigPath { $env:TEST_FALLBACK }
function Get-TemplateConfigPath { $env:TEST_TEMPLATE }
""" + functions + """
$config = Load-StarterConfig -RequiredFields @()
if ($config.apiVersion -ne $env:TEST_EXPECTED) { throw "Unexpected version: $($config.apiVersion)" }
"""
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-Command", script],
                        env={**os.environ, "TEST_LOCAL": str(local), "TEST_FALLBACK": str(fallback),
                             "TEST_TEMPLATE": str(STARTER / "config.template.json"), "TEST_EXPECTED": expected},
                        capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)


class StarterKnowledgeBaseTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_input_validation_matches_selected_api(self):
        function = "function Resolve-KnowledgeBaseInput" + STARTER_SOURCE.split(
            "function Resolve-KnowledgeBaseInput", 1,
        )[1].split("function New-StarterRun", 1)[0]
        for version, kb_id, valid in (
            ("2026-06-01", GA_ID, True),
            ("2026-06-01", PREVIEW_ID, False),
            ("2026-02-01-preview", GA_ID, True),
            ("2026-02-01-preview", PREVIEW_ID, True),
            ("2026-06-01", GA_ID + "/unexpected", False),
            ("2026-06-01", "/bookshelves/{{library}}/knowledgeBases/reference", False),
            ("2026-02-01-preview", "/bookshelves/<library>/knowledgeBases/reference", False),
        ):
            with self.subTest(version=version, kb_id=kb_id):
                script = "$ErrorActionPreference = 'Stop'\n" + function + """
$requirements = @(@{ agent = 'TestAgent'; knowledgeBases = @(@{}) })
Resolve-KnowledgeBaseInput -Requirements $requirements -InputJson $env:TEST_KBS -ApiVersion $env:TEST_API | Out-Null
"""
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-Command", script],
                    env={**os.environ, "TEST_KBS": json.dumps({"TestAgent": [{"knowledgeBaseId": kb_id}]}), "TEST_API": version},
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_deployment_binding_matches_selected_api(self):
        script = STARTER_SOURCE.split("def tool_leaf(", 1)[1].split("def write_agent_yaml(", 1)[0]
        script = "def tool_leaf(" + script
        ast.parse(script)
        for version, kb_id, valid in (
            ("2026-06-01", GA_ID, True),
            ("2026-06-01", PREVIEW_ID, False),
            ("2026-02-01-preview", GA_ID, True),
            ("2026-02-01-preview", PREVIEW_ID, True),
            ("2026-06-01", "/bookshelves/{{library}}/knowledgeBases/reference", False),
            ("2026-02-01-preview", "/bookshelves/<library>/knowledgeBases/reference", False),
        ):
            for provided in (False, True):
                with self.subTest(version=version, kb_id=kb_id, provided=provided), tempfile.TemporaryDirectory() as directory:
                    agent = Path(directory) / "agent.yaml"
                    kbs = [{"knowledgeBaseId": kb_id}]
                    agent.write_text(yaml.safe_dump({
                        "name": "TestAgent",
                        "discoveryExtensions": {"knowledgeBases": kbs},
                    }), encoding="utf-8")
                    context = {
                        "copy": copy, "yaml": yaml, "re": re,
                        "cfg": {"apiVersion": version},
                        "plan": {"knowledgeBases": {"TestAgent": kbs} if provided else {}},
                    }
                    exec(compile(script, str(STARTER), "exec"), context)
                    if valid:
                        doc = context["patch_agent_doc"]({"name": "TestAgent", "agentYaml": str(agent)})
                        self.assertEqual(doc["discoveryExtensions"]["knowledgeBases"], kbs)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "knowledgeBases"):
                            context["patch_agent_doc"]({"name": "TestAgent", "agentYaml": str(agent)})


class ConfirmationSettingsTests(unittest.TestCase):
    def test_agent_without_existing_extensions_disables_plan_confirmation(self):
        patch_script = AGENT_SOURCE.split("$PatchPy = Join-Path", 1)[1].split("@'\n", 1)[1].split("\n'@ | Set-Content $PatchPy", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent.yaml"
            path.write_text("name: NoToolAgent\nmodel:\n  id: '{{CHAT-MODEL}}'\n", encoding="utf-8")
            result = subprocess.run(
                [shutil.which("python") or "python", "-c", patch_script, str(path), "model"],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["discoveryExtensions"], {"humanInTheLoop": "Disabled"})

    def test_agent_upsert_payload_retains_disabled_settings(self):
        script = "def build_prompt_definition(" + AGENT_SOURCE.split(
            "def build_prompt_definition(", 1,
        )[1].split("def upsert_agent(", 1)[0]
        context = {}
        exec(compile(script, str(AGENT), "exec"), context)
        payload = context["build_payload"]({
            "name": "Example", "model": {"id": "model"},
            "discoveryExtensions": {
                "humanInTheLoop": "Disabled",
                "tools": [{"toolId": "tool-id", "confirmation": "Disabled"}],
            },
        })
        self.assertEqual(payload["humanInTheLoop"], "Disabled")
        self.assertEqual(payload["tools"], [{"toolId": "tool-id", "confirmation": "Disabled"}])

    def test_agent_patch_disables_all_confirmations_and_preserves_bindings(self):
        patch_script = AGENT_SOURCE.split("$PatchPy = Join-Path", 1)[1].split("@'\n", 1)[1].split("\n'@ | Set-Content $PatchPy", 1)[0]
        deployed_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/tools/test"
        other_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/tools/other"
        for tool_id in (deployed_id, ""):
            with self.subTest(tool_id=tool_id), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "agent.yaml"
                source = {
                    "name": "Example", "model": {"id": "{{CHAT-MODEL}}"},
                    "discoveryExtensions": {
                        "humanInTheLoop": "Enabled",
                        "tools": [
                            {"toolId": deployed_id, "confirmation": "Enabled"},
                            {"toolId": other_id, "confirmation": "Enabled"},
                        ],
                        "knowledgeBases": [{"knowledgeBaseId": GA_ID}],
                    },
                }
                path.write_text(yaml.safe_dump(source), encoding="utf-8")
                result = subprocess.run(
                    [shutil.which("python") or "python", "-c", patch_script, str(path), "model", tool_id],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                doc = yaml.safe_load(path.read_text(encoding="utf-8"))
                ext = doc["discoveryExtensions"]
                self.assertEqual(ext["humanInTheLoop"], "Disabled")
                self.assertEqual([x["toolId"] for x in ext["tools"]], [deployed_id, other_id])
                self.assertTrue(all(x["confirmation"] == "Disabled" for x in ext["tools"]))
                self.assertEqual(ext["knowledgeBases"], source["discoveryExtensions"]["knowledgeBases"])

    def test_starter_patch_disables_confirmations_even_for_existing_tools(self):
        script = "def tool_leaf(" + STARTER_SOURCE.split("def tool_leaf(", 1)[1].split("def write_agent_yaml(", 1)[0]
        deployed_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/tools/test"
        other_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/tools/other"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent.yaml"
            path.write_text(yaml.safe_dump({
                "name": "Example",
                "discoveryExtensions": {
                    "humanInTheLoop": "Enabled",
                    "tools": [
                        {"toolId": deployed_id, "confirmation": "Enabled"},
                        {"toolId": other_id, "confirmation": "Enabled"},
                    ],
                },
            }), encoding="utf-8")
            context = {
                "copy": copy, "yaml": yaml, "re": re, "cfg": {"apiVersion": "2026-06-01"},
                "plan": {"tools": [{"agent": "Example", "toolResourceId": deployed_id}]},
            }
            exec(compile(script, str(STARTER), "exec"), context)
            ext = context["patch_agent_doc"]({"name": "Example", "agentYaml": str(path)})["discoveryExtensions"]
            self.assertEqual(ext["humanInTheLoop"], "Disabled")
            self.assertEqual([x["toolId"] for x in ext["tools"]], [deployed_id, other_id])
            self.assertTrue(all(x["confirmation"] == "Disabled" for x in ext["tools"]))

    def test_starter_upsert_payload_retains_disabled_settings(self):
        functions = "def tool_leaf(" + STARTER_SOURCE.split(
            "def tool_leaf(", 1,
        )[1].split("rows = []", 1)[0]
        tool_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Discovery/tools/test"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent.yaml"
            path.write_text(yaml.safe_dump({
                "name": "Example",
                "discoveryExtensions": {
                    "humanInTheLoop": "Enabled",
                    "tools": [{"toolId": tool_id, "confirmation": "Enabled"}],
                },
            }), encoding="utf-8")
            response = Mock(status_code=200, headers={"content-type": "application/json"})
            response.json.return_value = {}
            requests = Mock()
            requests.post.return_value = response
            context = {
                "copy": copy, "yaml": yaml, "re": re, "os": os, "json": json,
                "requests": requests, "token": lambda: "token",
                "prompt_definition": lambda doc: {"kind": "prompt", "model": "model"},
                "cfg": {"apiVersion": "2026-06-01", "workspaceEndpoint": "https://example.test", "project": "test"},
                "plan": {"outputDir": directory, "tools": [{"agent": "Example", "toolResourceId": tool_id}]},
            }
            exec(compile(functions, str(STARTER), "exec"), context)
            context["deploy_agent"]({"name": "Example", "agentYaml": str(path)})
            payload = requests.post.call_args.kwargs["json"]
            self.assertEqual(payload["humanInTheLoop"], "Disabled")
            self.assertEqual(payload["tools"], [{"toolId": tool_id, "confirmation": "Disabled"}])


if __name__ == "__main__":
    unittest.main()
