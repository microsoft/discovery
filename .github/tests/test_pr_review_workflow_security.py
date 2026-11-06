"""Security contracts for read-only PR validation and privileged reporting."""

import json
from pathlib import Path
import re
import subprocess

import pytest
import yaml

from validate_pr import check_contributor_scope


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "workflows" / "pr-review.yml"
REPORT_WORKFLOW_PATH = WORKFLOW_PATH.with_name("pr-review-report.yml")
CODEOWNERS_PATH = Path(__file__).resolve().parents[1] / "CODEOWNERS"
REMOVAL_WORKFLOW_PATH = WORKFLOW_PATH.with_name("check-agent-removal-impact.yml")


def load_workflow(path: Path = WORKFLOW_PATH) -> dict:
    document = yaml.load(
        path.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert isinstance(document, dict)
    return document


def is_checkout(step: dict) -> bool:
    return step.get("uses", "").partition("@")[0] == "actions/checkout"


def test_untrusted_jobs_do_not_checkout_before_shell_execution():
    workflow = load_workflow()

    classify_steps = workflow["jobs"]["classify"]["steps"]
    assert not any(is_checkout(step) for step in classify_steps)
    assert "pulls.listFiles" in classify_steps[0]["with"]["script"]

    secret_steps = workflow["jobs"]["secret-scan"]["steps"]
    assert not any(is_checkout(step) for step in secret_steps)
    command = secret_steps[0]["run"]
    assert "git init /tmp/pr-history" in command
    assert "git init --bare" not in command
    assert "git -C /tmp/pr-history read-tree --empty" in command
    assert '"$BASE_SHA:refs/heads/trufflehog-base"' in command
    assert '"$HEAD_SHA:refs/heads/trufflehog-head"' in command
    assert "trufflehog git file:///tmp/pr-history" in command


def test_author_trust_signals_are_passed_to_validator():
    workflow = load_workflow()
    classify = workflow["jobs"]["classify"]
    permission_step = next(
        step for step in classify["steps"] if step.get("id") == "author_permission"
    )

    assert "getCollaboratorPermissionLevel" in permission_step["with"]["script"]
    assert classify["outputs"]["author_permission"] == (
        "${{ steps.author_permission.outputs.permission }}"
    )
    assert classify["outputs"]["author_association"] == (
        "${{ steps.author_permission.outputs.association }}"
    )
    assert "github.rest.pulls.get" in permission_step["with"]["script"]
    assert "response.data.author_association" in permission_step["with"]["script"]

    validator = next(
        step
        for step in workflow["jobs"]["validate"]["steps"]
        if step.get("id") == "run_validator"
    )
    assert validator["env"]["PR_AUTHOR_PERMISSION"] == (
        "${{ needs.classify.outputs.author_permission || 'unknown' }}"
    )
    assert validator["env"]["PR_AUTHOR_ASSOCIATION"] == (
        "${{ needs.classify.outputs.author_association || 'NONE' }}"
    )


@pytest.mark.parametrize(("permission_status", "association_status"), [
    (0, 0),
    (404, 0),
    (403, 0),
    (0, 403),
])
def test_author_trust_resolution_does_not_open_protected_utility_scope(
    permission_status, association_status,
):
    classify = load_workflow()["jobs"]["classify"]
    script = next(
        step["with"]["script"] for step in classify["steps"]
        if step.get("id") == "author_permission"
    )
    harness = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const outputs = {}, warnings = [], calls = [], infos = [];
const core = {
  setOutput: (key, value) => outputs[key] = value,
  warning: message => warnings.push(message),
  info: message => infos.push(message),
};
const respond = async (name, options, status, data) => {
  calls.push({name, options});
  if (status) throw Object.assign(new Error('Lookup unavailable'), {status});
  return {data};
};
const github = {rest: {
  repos: {getCollaboratorPermissionLevel: async options =>
    respond('permission', options, input.permission_status, {permission: 'read'})},
  pulls: {get: async options =>
    respond('association', options, input.association_status, {author_association: 'NONE'})},
}};
const context = {
  repo: {owner: 'microsoft', repo: 'discovery'},
  payload: {pull_request: {
    number: 103, user: {login: 'Modrats'}, author_association: 'MEMBER',
  }},
};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('core', 'github', 'context', input.script)(core, github, context)
  .then(() => console.log(JSON.stringify({outputs, warnings, calls, infos})))
  .catch(error => {console.error(error); process.exitCode = 1;});
"""
    process = subprocess.run(
        ["node", "-e", harness],
        input=json.dumps({
            "script": script,
            "permission_status": permission_status,
            "association_status": association_status,
        }),
        capture_output=True, text=True,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["outputs"] == {
        "permission": (
            "none" if permission_status == 404
            else "unknown" if permission_status else "read"
        ),
        "association": "NONE",
    }
    assert result["calls"] == [
        {"name": "permission", "options": {
            "owner": "microsoft", "repo": "discovery", "username": "Modrats",
        }},
        {"name": "association", "options": {
            "owner": "microsoft", "repo": "discovery", "pull_number": 103,
        }},
    ]
    assert len(result["warnings"]) == (
        int(permission_status not in {0, 404}) + int(bool(association_status))
    )
    assert any("does not prove non-membership" in info for info in result["infos"])
    public_paths = [
        ".gitignore", "README.md", "skills/example/scripts/helper.cjs",
    ]
    assert check_contributor_scope(
        public_paths, result["outputs"]["permission"], "Modrats",
        author_association=result["outputs"]["association"],
    ) == []
    protected_paths = [
        ".github/workflows/example.yml", "utilities/terraform/main.tf",
        "utilities/terraform/.terraform.lock.hcl", "utilities/README.md",
    ]
    failures = check_contributor_scope(
        protected_paths, result["outputs"]["permission"],
        "Modrats", author_association=result["outputs"]["association"],
    )
    assert [(failure.rule_id, failure.file) for failure in failures] == [
        ("POL-021", path) for path in protected_paths
    ]


def test_reporter_executes_only_default_branch_code():
    workflow = load_workflow(REPORT_WORKFLOW_PATH)
    assert workflow["on"] == {
        "workflow_run": {"workflows": ["PR Review", "Check Agent Removal Impact"], "types": ["completed"]},
    }
    job = workflow["jobs"]["report"]
    assert "workflow_run.event == 'pull_request'" in job["if"]
    assert "workflow_run.conclusion != 'cancelled'" in job["if"]
    checkouts = [step for step in job["steps"] if is_checkout(step)]
    assert len(checkouts) == 1
    assert checkouts[0]["with"] == {
        "ref": "${{ github.sha }}", "path": "trusted",
        "fetch-depth": "1", "persist-credentials": "false",
    }
    assert job["steps"][-1]["run"] == "python trusted/.github/scripts/report_pr_review.py"
    assert job["steps"][-1]["env"] == {"GH_TOKEN": "${{ secrets.GITHUB_TOKEN }}"}
    source = REPORT_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "workflow_run.head_sha" not in source
    assert "actions/download-artifact" not in source
    assert "cache:" not in source
    assert "workflow_run.workflow_id" in workflow["concurrency"]["group"]
    assert workflow["concurrency"]["cancel-in-progress"] == "false"


def test_required_check_names_and_attempt_scoped_handoff_are_preserved():
    workflow = load_workflow()
    assert workflow["on"] == {
        "pull_request": {"branches": ["main"], "types": ["opened", "synchronize", "reopened"]},
    }
    assert {job["name"] for job in workflow["jobs"].values()} == {
        "Classify Changed Paths", "Validate PR", "Secret Scan", "Post Results",
    }
    handoff = workflow["jobs"]["post-results"]
    assert handoff["if"] == "${{ !cancelled() }}"
    assert set(handoff["needs"]) == {"classify", "validate", "secret-scan"}
    download, upload, _ = handoff["steps"]
    assert download["with"]["name"] == "validation-results"
    assert "continue-on-error" not in download
    assert upload["with"] == {
        "name": "pr-review-report-${{ github.run_attempt }}",
        "path": "${{ runner.temp }}/pr-review-report/validation-results.json",
        "if-no-files-found": "error",
    }
    assert "results_json" not in WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", [WORKFLOW_PATH, REPORT_WORKFLOW_PATH])
def test_review_workflows_pin_actions_and_use_ephemeral_runners(path):
    assert set(re.findall(
        r"secrets\.([A-Z_][A-Z0-9_]*)", path.read_text(encoding="utf-8")
    )) == {"GITHUB_TOKEN"}
    for job in load_workflow(path)["jobs"].values():
        assert job["runs-on"] == "ubuntu-latest"
        assert 0 < int(job["timeout-minutes"]) <= 20
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", step["uses"])


def owners_for_path(path: str) -> list[str]:
    owners = []
    for line in CODEOWNERS_PATH.read_text(encoding="utf-8").splitlines():
        fields = line.partition("#")[0].split()
        if not fields:
            continue
        pattern = fields[0]
        # This policy uses only a global default and rooted, wildcard-free
        # directory (trailing "/") or exact-file overrides.
        assert pattern == "*" or (
            pattern.startswith("/") and "*" not in pattern
        )
        if pattern == "*":
            matches = True
        elif pattern.endswith("/"):
            matches = path.startswith(pattern[1:])
        else:
            matches = path == pattern[1:]
        if matches:
            owners = fields[1:]
    return owners


@pytest.mark.parametrize("path", [
    "README.md",
    "docs/ordinary-guide.md",
    ".github/CODEOWNERS",
    ".github/skills/demo/SKILL.md",
    "skills-other/demo/scripts/build.sh",
    ".github/workflows/pr-review.yml",
    ".github/scripts/validate_pr.py",
    ".github/tests-other/test_example.py",
    ".github/policy/baseline.json",
    ".github/dependabot.yml",
    ".github/requirements-other.txt",
    ".github/scripts/requirements-ci.txt",
    ".config/other-tool.json",
    "docs/validation-baseline-debt.md",
    "docs/schemas/agent.schema.json",
    ".auto-registry/agents.json",
    "new-directory/nested/file.txt",
    "docs/utilities/file.py",
    "utilities-other/file.py",
    "utilities/discovery-toolbox/README.md",
    "utilities/discovery-toolbox/vsix/DiscoveryToolbox-v1.0.0.vsix",
    "utilities/discovery-toolbox/new-directory/file.txt",
])
def test_non_utilities_and_toolbox_use_default_maintainers(path):
    assert owners_for_path(path) == ["@microsoft/discovery-samples-maintainer"]


@pytest.mark.parametrize("path", [
    "utilities/README.md",
    "utilities/supercomputer-cli/main.py",
    "utilities/new-utility/nested/script.ps1",
    "utilities/discovery-toolbox-other/file.py",
])
def test_utilities_use_engineering_reviewers(path):
    assert owners_for_path(path) == ["@microsoft/discovery-engineering-reviewers"]


@pytest.mark.parametrize("path", [
    ".github/tests/test_pr_review_workflow_security.py",
    ".github/tests/rules/test_pol_016.py",
    ".github/requirements-ci.txt",
    ".config/dotnet-tools.json",
    "agents/molecule-visualization/agent.yaml",
    "starter-kits/example/kit.json",
    "skills/example/SKILL.md",
    "skills/example/scripts/build.sh",
    "skills/example/templates/main.tex",
])
def test_catalog_and_tests_allow_contributions_reviewers(path):
    assert owners_for_path(path) == [
        "@microsoft/discovery-samples-maintainer",
        "@microsoft/discovery-contributions-reviewers",
    ]


def test_trufflehog_install_and_repository_layout_are_stable():
    workflow = load_workflow()
    command = workflow["jobs"]["secret-scan"]["steps"][0]["run"]

    assert (
        "trufflesecurity/trufflehog/"
        "cc1fe982afc515d2991365ce8d4d0dd07170fcad/scripts/install.sh"
        in command
    )
    assert "sh -s -- -b /usr/local/bin v3.97.2" in command
    assert "trufflesecurity/trufflehog/main/scripts/install.sh" not in command
    assert "/tmp/pr-history.git" not in command


def test_only_separate_reporting_workflow_has_write_permissions():
    workflow = load_workflow()
    assert workflow["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
    }

    for job in workflow["jobs"].values():
        assert "permissions" not in job
    assert "pull_request_target" not in WORKFLOW_PATH.read_text(encoding="utf-8")

    assert load_workflow(REPORT_WORKFLOW_PATH)["permissions"] == {
        "contents": "read",
        "actions": "read",
        "pull-requests": "write",
        "issues": "write",
    }


def test_validation_checkouts_do_not_persist_privileged_credentials():
    workflow = load_workflow()
    checkouts = [
        step
        for step in workflow["jobs"]["validate"]["steps"]
        if is_checkout(step)
    ]
    assert len(checkouts) == 2
    assert all(step["with"]["persist-credentials"] == "false" for step in checkouts)

    untrusted = next(step for step in checkouts if step["with"].get("path") == "pr")
    assert untrusted["with"]["repository"] == (
        "${{ github.event.pull_request.head.repo.full_name }}"
    )
    assert untrusted["with"]["ref"] == "${{ github.event.pull_request.head.sha }}"
    assert "allow-unsafe-pr-checkout" not in untrusted["with"]


def test_removal_gate_is_read_only_and_keeps_its_required_identity_and_scope():
    workflow = load_workflow(REMOVAL_WORKFLOW_PATH)
    assert workflow["on"] == {"pull_request": ""}
    assert workflow["permissions"] == {"contents": "read", "pull-requests": "read"}
    job = workflow["jobs"]["check-impact"]
    assert job["name"] == "Check if agent removal breaks starter kits"
    assert "permissions" not in job
    steps = job["steps"]
    classification = steps[0]
    assert classification["id"] == "changes" and not any(is_checkout(s) for s in steps[:1])
    assert "github.paginate" in classification["with"]["script"]
    gate = next(s for s in steps if s.get("id") == "gate")
    assert gate["if"] == "steps.changes.outputs.relevant == 'true'"
    assert "continue-on-error" not in gate
    assert "python trusted/.github/scripts/check_agent_removal_impact.py" in gate["run"]
    assert "--report-json" in gate["run"] and "--base-registry-root trusted" in gate["run"]
    assert gate["env"]["GITHUB_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"
    assert set(re.findall(
        r"secrets\.([A-Z_][A-Z0-9_]*)", REMOVAL_WORKFLOW_PATH.read_text(encoding="utf-8")
    )) == {"GITHUB_TOKEN"}
    checkouts = [s["with"] for s in steps if is_checkout(s)]
    assert all(c["persist-credentials"] == "false" and "allow-unsafe-pr-checkout" not in c for c in checkouts)


def test_removal_handoff_preserves_gate_failure_and_is_optional_transport_only():
    steps = load_workflow(REMOVAL_WORKFLOW_PATH)["jobs"]["check-impact"]["steps"]
    finalize = next(s for s in steps if s["name"] == "Finalize removal report")
    assert finalize["if"] == "${{ !cancelled() }}"
    assert finalize["env"] == {
        "CLASSIFICATION_OUTCOME": "${{ steps.changes.outcome }}",
        "RELEVANT": "${{ steps.changes.outputs.relevant }}",
        "GATE_OUTCOME": "${{ steps.gate.outcome }}",
    }
    assert "core.setFailed" in finalize["with"]["script"]
    upload = next(s for s in steps if s.get("id") == "upload")
    assert upload["if"] == "${{ !cancelled() }}" and upload["continue-on-error"] == "true"
    assert upload["with"] == {
        "name": "agent-removal-report-${{ github.run_attempt }}",
        "path": "${{ runner.temp }}/agent-removal-report/agent-removal-results.json",
        "if-no-files-found": "error",
    }
    warning = steps[-1]
    assert warning["if"] == "${{ !cancelled() && steps.upload.outcome == 'failure' }}"
    assert "::warning::" in warning["run"] and "GITHUB_STEP_SUMMARY" in warning["run"]
