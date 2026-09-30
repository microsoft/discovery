"""Security contracts for the privileged PR review workflow."""

from pathlib import Path

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


def test_codeowners_targets_sensitive_paths_without_global_fanout():
    active_lines = [
        line.strip()
        for line in CODEOWNERS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert not any(line.split(maxsplit=1)[0] == "*" for line in active_lines)
    assert any(line.startswith("/.github/") for line in active_lines)
    assert any(line.startswith("/docs/schemas/") for line in active_lines)
    assert not any(
        line.split(maxsplit=1)[0] == "/utilities/"
        for line in active_lines
    )
    assert any(
        line.startswith("/utilities/supercomputer-cli/")
        for line in active_lines
    )
    assert not any(
        line.startswith("/utilities/discovery-toolbox/")
        for line in active_lines
    )


def test_manifest_auto_approval_is_narrow_and_check_gated():
    source = AUTO_MERGE_PATH.read_text(encoding="utf-8")

    assert "classify_fastlane.py" in source
    assert "manifest_auto_approval" in source
    assert "toolbox_one_approval" in source
    assert "can_approve_pull_request_reviews" in source
    assert "Microsoft WinGet manifest automation" in source
    assert 'if [ "$MANIFEST_FAST_LANE" = "true" ]' in source
    assert 'if [ "$CHECKS_PASSED" = "true" ]' in source
    assert "author_association" in source
    assert "Evaluate PR gates and merge when ready" in source


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
