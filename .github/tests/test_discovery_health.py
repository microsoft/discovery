"""Discovery Health harness: PowerShell suites, workflow contracts and deployer parity.

The harness lives in .github/discovery-health (PowerShell 7). These tests run its
offline suites (fake Azure backend), pin the security shape of its workflows, and
check that its API payload and receipt logic match the agent deployer skill.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
HEALTH = REPO_ROOT / ".github" / "discovery-health"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
DEPLOYER = REPO_ROOT / ".github" / "skills" / "discovery-services-agent-deployer" / "scripts" / "deploy-discovery-agent.ps1"
MAIN_WORKFLOW = WORKFLOWS / "discovery-health.yml"
CLEANUP_WORKFLOW = WORKFLOWS / "discovery-health-cleanup.yml"
PWSH = shutil.which("pwsh")


def require_pwsh() -> str:
    if PWSH:
        return PWSH
    if os.environ.get("CI") == "true":
        pytest.fail("PowerShell 7 (pwsh) is required in CI for the Discovery Health suites")
    pytest.skip("PowerShell 7 (pwsh) is not installed")
    return ""


def load_workflow(path: Path) -> dict[str, Any]:
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def steps_of(job: dict[str, Any]) -> list[dict[str, Any]]:
    return job.get("steps", [])


def uses(step: dict[str, Any], action: str) -> bool:
    return step.get("uses", "").partition("@")[0] == action


# ---------------------------------------------------------------------------
# PowerShell suites (offline; fake ARM/ACR/Discovery backend)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("suite", ["Unit.Tests.ps1", "Scheduler.Tests.ps1"])
def test_powershell_suite(suite: str) -> None:
    pwsh = require_pwsh()
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(HEALTH / "tests" / suite)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    lines = [line for line in result.stdout.splitlines() if line.startswith(("PASS", "FAIL", "SUMMARY", "at "))]
    assert result.returncode == 0, "\n".join(lines[-80:]) + "\n" + result.stderr[-4000:]
    assert any(line.startswith("SUMMARY") for line in lines)


def test_cli_plan_is_offline_and_writes_matrix(tmp_path: Path) -> None:
    pwsh = require_pwsh()
    out = tmp_path / "plan"
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(HEALTH / "Invoke-DiscoveryHealth.ps1"), "plan",
         "-Agents", "chembl,online-researcher", "-Shards", "2", "-OutputDir", str(out)],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        env={**os.environ, "AZURE_CONFIG_DIR": str(tmp_path / "no-azure")},
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    matrix = json.loads((out / "matrix.json").read_text(encoding="utf-8"))
    assert set(plan["agents"]) == {"chembl", "online-researcher"}
    assert {entry["shard"] for entry in matrix["include"]} <= {1, 2}
    expected = {(item["tool"], item["stage"]) for item in plan["agents"]["chembl"]["expected"]}
    assert ("ChEMBL", "build") in expected and ("", "round-trip") in expected


# ---------------------------------------------------------------------------
# Workflow contracts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [MAIN_WORKFLOW, CLEANUP_WORKFLOW])
def test_workflows_only_run_trusted_events(path: Path) -> None:
    workflow = load_workflow(path)
    assert set(workflow["on"]) == {"schedule", "workflow_dispatch"}, "no pull_request/pull_request_target/workflow_run triggers"
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {"group": "discovery-health-live", "cancel-in-progress": "false"}


@pytest.mark.parametrize("path", [MAIN_WORKFLOW, CLEANUP_WORKFLOW])
def test_jobs_are_bounded_and_least_privileged(path: Path) -> None:
    workflow = load_workflow(path)
    allowed_writes = {
        "test": {"id-token"},
        "report": {"id-token"},
        "cleanup": {"id-token"},
        "publish": {"pages", "id-token"},
        "pr-feedback": {"pull-requests"},
    }
    for name, job in workflow["jobs"].items():
        assert job["runs-on"] == "ubuntu-latest", name
        assert 0 < int(job["timeout-minutes"]) <= 360, name
        permissions = job.get("permissions")
        assert isinstance(permissions, dict), f"{name} must declare explicit permissions"
        writes = {scope for scope, level in permissions.items() if level == "write"}
        assert writes <= allowed_writes.get(name, set()), f"{name} has unexpected write scopes {writes}"
        for step in steps_of(job):
            if uses(step, "actions/checkout"):
                assert step.get("with", {}).get("persist-credentials") == "false", f"{name} checkout persists credentials"


def test_azure_jobs_use_split_environments() -> None:
    jobs = load_workflow(MAIN_WORKFLOW)["jobs"]
    environment = jobs["test"]["environment"]
    assert "discovery-health-pr" in environment and "discovery-health-trusted" in environment
    assert "untrusted" in environment
    assert jobs["report"]["environment"] == "discovery-health-trusted"
    assert jobs["publish"]["environment"]["name"] == "github-pages"
    assert load_workflow(CLEANUP_WORKFLOW)["jobs"]["cleanup"]["environment"] == "discovery-health-trusted"
    for name in ("plan", "pr-feedback"):
        assert "environment" not in jobs[name]
        assert "id-token" not in jobs[name]["permissions"]


def test_pull_request_content_is_data_only() -> None:
    workflow = load_workflow(MAIN_WORKFLOW)
    for name, job in workflow["jobs"].items():
        checkouts = [step for step in steps_of(job) if uses(step, "actions/checkout")]
        pr_checkouts = [step for step in checkouts if step.get("with", {}).get("path") == "pr"]
        for step in pr_checkouts:
            assert "head_sha" in step["with"]["ref"], f"{name} must check out the verified PR SHA"
        commands = "\n".join(step.get("run", "") for step in steps_of(job))
        assert not re.search(r"(?:^|[\s&./])pr/[^\s'\"]*\.(?:ps1|py|sh)", commands), f"{name} executes PR files"
        if pr_checkouts:
            python = [step for step in steps_of(job) if uses(step, "actions/setup-python")]
            assert all("cache" not in step.get("with", {}) for step in python), f"{name} caches with PR data present"
    test_env = workflow["jobs"]["test"]["env"]
    assert "untrusted != 'true'" in test_env["DH_TEMPLATE_VARIABLES"], "secrets never reach PR runs"
    verify = next(step for step in steps_of(workflow["jobs"]["plan"]) if step.get("id") == "pr")
    assert "EXPECTED_SHA" in verify["run"] and "'open'" in verify["run"] and "'main'" in verify["run"]


def test_public_artifacts_exclude_private_evidence() -> None:
    workflow = load_workflow(MAIN_WORKFLOW)
    for job in workflow["jobs"].values():
        for step in steps_of(job):
            if uses(step, "actions/upload-artifact"):
                assert "evidence" not in step["with"]["path"], "raw evidence must stay in private storage"
                assert "operations" not in step["with"]["path"], "operation registry URLs contain resource ids"
                assert "/acr" not in step["with"]["path"] and "/catalog" not in step["with"]["path"]


def test_scorecard_publishes_only_from_main_and_never_for_prs() -> None:
    workflow = load_workflow(MAIN_WORKFLOW)
    plan_step = next(step for step in steps_of(workflow["jobs"]["plan"]) if step.get("id") == "plan")
    assert "inputs.pr_number == ''" in plan_step["env"]["PUBLISH"]
    report_step = next(step for step in steps_of(workflow["jobs"]["report"]) if step.get("id") == "report")
    assert "refs/heads/main" in report_step["run"]
    assert workflow["jobs"]["publish"]["if"].count("site == 'true'") == 1


def test_unit_test_workflow_runs_for_harness_changes() -> None:
    unit = (WORKFLOWS / "unit-tests.yml").read_text(encoding="utf-8")
    assert '".github/discovery-health/**"' in unit
    assert "discovery-health" in unit.split("grep -E", 1)[1].split("\n", 1)[0]


# ---------------------------------------------------------------------------
# Parity with the agent deployer skill (its embedded Python is the reference)
# ---------------------------------------------------------------------------


def _embedded_python(marker: str) -> str:
    source = DEPLOYER.read_text(encoding="utf-8")
    start = source.index(marker)
    body_start = source.index("@'\n", start) + 3
    body_end = source.index("\n'@", body_start)
    return source[body_start:body_end]


def _deployer_payload(agent_yaml: Path, tool_id: str, config: dict[str, str]) -> dict[str, Any]:
    import tempfile

    patch = _embedded_python("$PatchPy = Join-Path $RunDir 'patch_agent_yaml.py'")
    deploy = _embedded_python("$DeployScript = Join-Path $RunDir 'stage-04a-deploy-agent.py'")
    namespace: dict[str, Any] = {"__name__": "deployer_reference"}
    exec(compile(deploy, "stage-04a-deploy-agent.py", "exec"), namespace)
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "agent.yaml"
        shutil.copyfile(agent_yaml, target)
        subprocess.run(["python", "-c", patch, str(target), config["model"], tool_id], check=True, text=True)
        document = namespace["resolve_variables"](namespace["load_yaml"](str(target)), config)
    return namespace["build_payload"](document)


PARITY_AGENTS = ["chembl", "aizynthfinder", "alphafold-db", "openmm", "rdock", "pubchem", "biopython", "tmalign"]


@pytest.mark.parametrize("agent", PARITY_AGENTS)
def test_agent_payload_matches_deployer(agent: str, tmp_path: Path) -> None:
    pwsh = require_pwsh()
    agent_yaml = REPO_ROOT / "agents" / agent / "agent.yaml"
    document = yaml.safe_load(agent_yaml.read_text(encoding="utf-8"))
    placeholders = [t["toolId"] for t in document["discoveryExtensions"]["tools"]]
    assert len(placeholders) == 1, "parity sample uses single-tool agents"
    tool_id = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Discovery/tools/" + re.sub(r"[^a-z0-9]", "", agent)
    config = {
        "workspaceEndpoint": "https://ws.example", "apiVersion": "2026-06-01", "project": "proj", "model": "gpt-test",
        "tenantId": "tenant", "resourceGroup": "/subscriptions/s/resourceGroups/rg", "corePythonToolId": tool_id,
    }
    expected = _deployer_payload(agent_yaml, tool_id, config)
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module '{(HEALTH / 'DiscoveryHealth.psd1').as_posix()}' -Force
$m = Get-Module DiscoveryHealth
& $m {{
  $doc = ConvertFrom-DhYamlFile -Path '{agent_yaml.as_posix()}'
  $doc = Update-DhAgentDocument -Doc $doc -ChatModel 'gpt-test' -ToolIdMap @{{ '{placeholders[0]}' = '{tool_id}' }}
  $vars = @{{ workspaceEndpoint = 'https://ws.example'; apiVersion = '2026-06-01'; project = 'proj'; model = 'gpt-test'; tenantId = 'tenant'; resourceGroup = '/subscriptions/s/resourceGroups/rg'; corePythonToolId = '{tool_id}' }}
  $doc = Resolve-DhTemplateVariables -Value $doc -Variables $vars
  [Console]::Out.Write((ConvertTo-DhJson (New-DhAgentPayload -Doc $doc) -Compress))
}}
"""
    script_path = tmp_path / "payload.ps1"
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-File", str(script_path)], cwd=REPO_ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert result.returncode == 0, result.stderr[-3000:]
    actual = json.loads(result.stdout)
    assert actual == json.loads(json.dumps(expected))


def _deployer_verify_receipt():
    source = DEPLOYER.read_text(encoding="utf-8")
    start = source.index("def verify_receipt(text):")
    end = source.index("def assess_response(body):", start)
    namespace: dict[str, Any] = {}
    exec("import json, math, re\n" + source[start:end], namespace)
    return namespace["verify_receipt"]


RECEIPTS = [
    'DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"s","actual":2.1,"expected":2.1,"tolerance":1e-8}],"artifacts":[{"path":"/output/c.csv","bytes":12}]}',
    'DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"s","actual":"a","expected":"a"}],"artifacts":[{"path":"/output/c","bytes":1}]}',
    'DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"s","actual":1.0,"expected":3.0,"tolerance":0.5}],"artifacts":[{"path":"/output/c","bytes":1}]}',
    'DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"s","actual":true,"expected":"true"}],"artifacts":[{"path":"/output/c","bytes":1}]}',
    'DISCOVERY_VALIDATION_RESULT={"checks":[],"artifacts":[{"path":"/output/c","bytes":1}]}',
    'DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"s","actual":1,"expected":1}],"artifacts":[{"path":"/tmp/c","bytes":1}]}',
    'DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"s","actual":1,"expected":1}],"artifacts":[{"path":"/output/../c","bytes":1}]}',
    'DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"s","actual":1,"expected":1}],"artifacts":[{"path":"/output/c","bytes":0}]}',
    'DISCOVERY_VALIDATION_RESULT={"checks":[{"name":"s","actual":1,"expected":1,"tolerance":-1}],"artifacts":[{"path":"/output/c","bytes":1}]}',
    "no receipt",
]


def test_receipt_verification_matches_deployer(tmp_path: Path) -> None:
    pwsh = require_pwsh()
    verify = _deployer_verify_receipt()
    expected = []
    for text in RECEIPTS:
        try:
            verify(text)
            expected.append(True)
        except (ValueError, TypeError, AttributeError, KeyError):
            expected.append(False)
    payload = tmp_path / "receipts.json"
    payload.write_text(json.dumps(RECEIPTS), encoding="utf-8")
    script = f"""
Import-Module '{(HEALTH / 'DiscoveryHealth.psd1').as_posix()}' -Force
$m = Get-Module DiscoveryHealth
$texts = Get-Content '{payload.as_posix()}' -Raw | ConvertFrom-Json
$out = foreach ($t in $texts) {{ (& $m {{ param($x) Test-DhValidationReceipt -Text $x -RequireOutputPrefix }} $t) -eq '' }}
[Console]::Out.Write((ConvertTo-Json -InputObject @($out) -Compress))
"""
    script_path = tmp_path / "receipts.ps1"
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-File", str(script_path)], cwd=REPO_ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected
