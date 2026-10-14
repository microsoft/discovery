"""Security contracts for the privileged PR review workflow."""

from pathlib import Path

import pytest
import yaml


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "workflows" / "pr-review.yml"
AUTO_MERGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "workflows"
    / "auto-merge-on-approval.yml"
)
CODEOWNERS_PATH = Path(__file__).resolve().parents[1] / "CODEOWNERS"


def load_workflow() -> dict:
    document = yaml.load(
        WORKFLOW_PATH.read_text(encoding="utf-8"),
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

    validator = next(
        step
        for step in workflow["jobs"]["validate"]["steps"]
        if step.get("id") == "run_validator"
    )
    assert validator["env"]["PR_AUTHOR_PERMISSION"] == (
        "${{ needs.classify.outputs.author_permission || 'unknown' }}"
    )
    assert validator["env"]["PR_AUTHOR_ASSOCIATION"] == (
        "${{ github.event.pull_request.author_association || 'NONE' }}"
    )


def test_validation_feedback_does_not_submit_blocking_bot_reviews():
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "event: 'COMMENT'" in workflow_text
    assert "event: 'REQUEST_CHANGES'" not in workflow_text
    assert "requestReviewers" not in workflow_text


def owners_for_path(path: str) -> list[str]:
    owners = []
    for line in CODEOWNERS_PATH.read_text(encoding="utf-8").splitlines():
        fields = line.partition("#")[0].split()
        if not fields:
            continue
        pattern = fields[0]
        # This policy uses only a global default and rooted directory overrides.
        assert pattern == "*" or (
            pattern.startswith("/") and pattern.endswith("/")
        )
        if pattern == "*" or path.startswith(pattern[1:]):
            owners = fields[1:]
    return owners


@pytest.mark.parametrize("path", [
    "README.md",
    "docs/ordinary-guide.md",
    ".github/CODEOWNERS",
    ".github/workflows/pr-review.yml",
    ".github/scripts/validate_pr.py",
    ".github/policy/baseline.json",
    "docs/validation-baseline-debt.md",
    "docs/schemas/agent.schema.json",
    ".auto-registry/agents.json",
    "agents/new-agent/README.md",
    "starter-kits/new-kit/kit.json",
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


def test_native_auto_merge_keeps_only_the_manifest_exception():
    source = AUTO_MERGE_PATH.read_text(encoding="utf-8")

    assert "actions/checkout" not in source
    assert "pull_request_target" in source
    assert "trustedAssociations.has(pr.author_association)" in source
    assert "files.length === 1" in source
    assert "docs\\/discovery-app\\/releases\\/manifests\\/" in source
    assert "['added', 'modified'].includes(files[0].status)" in source
    assert "'renamed'" not in source
    assert "actions/create-github-app-token@" in source
    assert "permission-pull-requests: write" in source
    assert "APPROVAL_TOKEN" in source
    assert "GH_TOKEN=\"$APPROVAL_TOKEN\" gh api" in source
    assert 'gh pr merge "$PR_NUMBER" --repo "$REPO" --auto --squash' in source
    assert "DEPENDABOT_FAST_LANE" not in source
    assert "TOOLBOX_FAST_LANE" not in source
    assert "HUMAN_APPROVALS" not in source
    assert "CHECKS_PASSED" not in source


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


def test_only_reporting_job_has_write_permissions():
    workflow = load_workflow()
    assert workflow["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
    }

    for job_name in ("classify", "validate", "secret-scan"):
        assert "permissions" not in workflow["jobs"][job_name]

    assert workflow["jobs"]["post-results"]["permissions"] == {
        "contents": "read",
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
