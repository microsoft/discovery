"""Contracts for retiring target-event execution exceptions."""

from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
SOURCES = ("check-agent-removal-impact.yml", "pr-review.yml")


def load_workflow(name: str) -> dict:
    path = ROOT / ".github" / "workflows" / name
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_no_workflow_uses_target_event_and_exception_is_retired():
    assert not (ROOT / ".github" / "policy" / "actions-execution.json").exists()
    for path in (ROOT / ".github" / "workflows").iterdir():
        if path.suffix in {".yml", ".yaml"}:
            assert "pull_request_target" not in load_workflow(path.name)["on"], path.name


@pytest.mark.parametrize("name", SOURCES)
def test_read_only_sources_use_pinned_actions_and_ephemeral_runners(name):
    workflow = load_workflow(name)
    assert workflow["permissions"] == {"contents": "read", "pull-requests": "read"}
    for job in workflow["jobs"].values():
        assert job["runs-on"] in {"ubuntu-latest", "ubuntu-slim"}
        assert 0 < int(job["timeout-minutes"]) <= 20
        assert "permissions" not in job
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", step["uses"])


@pytest.mark.parametrize("name", SOURCES)
def test_data_checkouts_are_isolated_from_trusted_code_and_credentials(name):
    checkouts = [
        step["with"]
        for job in load_workflow(name)["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
    ]
    assert len(checkouts) == 2
    trusted = next(c for c in checkouts if c["path"] == "trusted")
    untrusted = next(c for c in checkouts if c["path"] == "pr")
    assert all(c["persist-credentials"] == "false" for c in checkouts)
    assert all("allow-unsafe-pr-checkout" not in c for c in checkouts)
    assert trusted["ref"] == "${{ github.event.pull_request.base.sha }}"
    assert untrusted["repository"] == "${{ github.event.pull_request.head.repo.full_name }}"
    assert untrusted["ref"] == "${{ github.event.pull_request.head.sha }}"


@pytest.mark.parametrize("name", SOURCES)
def test_required_checks_are_not_filtered_out_by_changed_paths(name):
    event = load_workflow(name)["on"]["pull_request"] or {}
    assert "paths" not in event and "paths-ignore" not in event
    if name == "check-agent-removal-impact.yml":
        assert not event  # Keep default activities and all base branches.
