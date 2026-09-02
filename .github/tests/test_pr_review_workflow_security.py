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
    assert "git init --bare" in secret_steps[0]["run"]


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
