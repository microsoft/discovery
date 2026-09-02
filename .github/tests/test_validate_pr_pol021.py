"""POL-021 protects trusted code while keeping documentation public."""

from __future__ import annotations

import pytest

from validate_pr import check_contributor_scope


@pytest.mark.parametrize("permission", ["admin", "maintain", "write"])
def test_maintainer_permissions_allow_any_repository_path(permission: str) -> None:
    changed = ["README.md", ".github/workflows/pr-review.yml", "docs/guide.md"]

    assert check_contributor_scope(changed, permission, "maintainer") == []


@pytest.mark.parametrize("permission", ["none", "read", "triage", "unknown", ""])
def test_public_permissions_allow_catalog_and_documentation(permission: str) -> None:
    changed = [
        "agents/demo/metadata.yaml",
        "agents/demo/tools/tool/tool.yaml",
        "starter-kits/demo/kit.json",
        "README.md",
        "CONTRIBUTING.md",
        "docs/authoring-guides/guide.md",
        "docs/how-to-videos/walkthrough.mp4",
        "includes/media/screenshot.png",
        "utilities/example/README.md",
    ]

    assert check_contributor_scope(changed, permission, "contributor") == []


def test_public_mixed_scope_reports_each_disallowed_file() -> None:
    changed = [
        "agents/demo/metadata.yaml",
        "README.md",
        "docs/authoring-guides/guide.md",
        ".github/workflows/pr-review.yml",
        "docs/schemas/metadata-schema.json",
        "docs/validation-rules.md",
        "utilities/example/run.py",
        ".auto-registry/agent-registry.json",
        ".vscode/settings.json",
        ".gitignore",
        "scripts/new_validator.py",
    ]

    failures = check_contributor_scope(changed, "read", "octocat")

    assert [(failure.rule_id, failure.file) for failure in failures] == [
        ("POL-021", ".github/workflows/pr-review.yml"),
        ("POL-021", "docs/schemas/metadata-schema.json"),
        ("POL-021", "docs/validation-rules.md"),
        ("POL-021", "utilities/example/run.py"),
        ("POL-021", ".auto-registry/agent-registry.json"),
        ("POL-021", ".vscode/settings.json"),
        ("POL-021", ".gitignore"),
        ("POL-021", "scripts/new_validator.py"),
    ]
    assert all("@octocat" in failure.message for failure in failures)


@pytest.mark.parametrize(
    "path",
    [
        "agents/../README.md",
        "agents/\\../README.md",
        "agents///demo/metadata.yaml",
        "starter-kits/./demo/kit.json",
        "/agents/demo/metadata.yaml",
        "agents",
    ],
)
def test_public_scope_rejects_noncanonical_or_escaping_paths(path: str) -> None:
    failures = check_contributor_scope([path], "none", "octocat")

    assert [(failure.rule_id, failure.file) for failure in failures] == [
        ("POL-021", path),
    ]


def test_absent_permission_disables_pr_only_check_for_local_validation() -> None:
    assert check_contributor_scope(["README.md"], None) == []


def test_instruction_markdown_under_trusted_automation_is_not_public_docs() -> None:
    failures = check_contributor_scope(
        [".github/skills/example/SKILL.md"], "read", "octocat"
    )

    assert [failure.rule_id for failure in failures] == ["POL-021"]


@pytest.mark.parametrize(
    "author",
    ["github-actions[bot]", "discovery-registry-bot[bot]"],
)
def test_trusted_registry_refresh_bot_can_update_generated_files(author: str) -> None:
    failures = check_contributor_scope(
        [".auto-registry/agent-registry.json"],
        "none",
        author,
        "chore/registry-refresh-123",
    )

    assert failures == []


def test_registry_branch_name_does_not_exempt_public_user() -> None:
    failures = check_contributor_scope(
        [".auto-registry/agent-registry.json"],
        "none",
        "octocat",
        "chore/registry-refresh-123",
    )

    assert [failure.rule_id for failure in failures] == ["POL-021"]