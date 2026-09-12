"""Security contracts for the privileged PR review workflow."""

from pathlib import Path

import yaml


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "workflows" / "pr-review.yml"


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
