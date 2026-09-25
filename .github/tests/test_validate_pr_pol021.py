"""POL-021 protects trusted code while keeping documentation public."""

from __future__ import annotations

import pytest

from catalog_validation.runner import run_validation
from validate_pr import check_contributor_scope


@pytest.mark.parametrize("permission", ["admin", "maintain", "write"])
def test_maintainer_permissions_allow_any_repository_path(permission: str) -> None:
    changed = ["README.md", ".github/workflows/pr-review.yml", "docs/guide.md"]

    assert check_contributor_scope(changed, permission, "maintainer") == []


@pytest.mark.parametrize("permission", ["none", "read", "triage", "unknown", ""])
def test_public_permissions_allow_catalog_and_documentation(permission: str) -> None:
    changed = [
        "agents/demo/metadata.yaml",
        "starter-kits/demo/kit.json",
        "README.md",
        "CONTRIBUTING.md",
        "docs/authoring-guides/guide.md",
        "includes/media/screenshot.png",
        "utilities/example/README.md",
    ]

    assert check_contributor_scope(changed, permission, "contributor") == []


def test_public_mixed_scope_reports_each_disallowed_file() -> None:
    changed = [
        "agents/demo/metadata.yaml",
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
    assert check_contributor_scope([".github/workflows/new.yml"], None) == []


def test_non_catalog_validation_enforces_contributor_scope(tmp_path) -> None:
    result = run_validation(
        tmp_path,
        [".github/workflows/new.yml"],
        author_permission="read",
        author="octocat",
    )

    assert [failure.rule_id for failure in result.blocking] == ["POL-021"]


def test_public_contributor_cannot_add_executable_under_docs() -> None:
    failures = check_contributor_scope(
        ["docs/discovery-services/setup.sh"], "read", "octocat"
    )

    assert [failure.rule_id for failure in failures] == ["POL-021"]


def test_trusted_registry_refresh_bot_can_update_generated_files() -> None:
    failures = check_contributor_scope(
        [".auto-registry/agent-registry.json"],
        "none",
        "github-actions[bot]",
        "chore/registry-refresh-123",
    )

    assert failures == []


@pytest.mark.parametrize(
    ("path", "head_ref"),
    [
        (
            ".github/workflows/code-scan.yml",
            "dependabot/github_actions/actions/checkout-7.0.1",
        ),
        (
            ".github/workflows/weekly-deep-scan.yaml",
            "dependabot/github_actions/actions/setup-python-7.0.0",
        ),
        (
            ".github/requirements-ci.txt",
            "dependabot/pip/dot-github/pip-minor-patch-123",
        ),
        (
            ".config/dotnet-tools.json",
            "dependabot/nuget/dot-config/nuget-minor-patch-123",
        ),
    ],
)
def test_dependabot_can_update_configured_protected_manifests(
    path: str,
    head_ref: str,
) -> None:
    failures = check_contributor_scope(
        [path],
        "none",
        "dependabot[bot]",
        head_ref,
    )

    assert failures == []


@pytest.mark.parametrize(
    ("path", "author", "head_ref"),
    [
        (
            ".github/workflows/code-scan.yml",
            "octocat",
            "dependabot/github_actions/actions/checkout-7.0.1",
        ),
        (
            ".github/workflows/code-scan.yml",
            "dependabot[bot]",
            "feature/update-checkout",
        ),
        (
            ".github/dependabot.yml",
            "dependabot[bot]",
            "dependabot/github_actions/actions/checkout-7.0.1",
        ),
        (
            ".github/workflows/nested/code-scan.yml",
            "dependabot[bot]",
            "dependabot/github_actions/actions/checkout-7.0.1",
        ),
        (
            ".github/requirements-ci.txt",
            "dependabot[bot]",
            "dependabot/nuget/dot-config/nuget-minor-patch-123",
        ),
    ],
)
def test_dependabot_exception_rejects_spoofed_or_unconfigured_changes(
    path: str,
    author: str,
    head_ref: str,
) -> None:
    failures = check_contributor_scope([path], "none", author, head_ref)

    assert [(failure.rule_id, failure.file) for failure in failures] == [
        ("POL-021", path),
    ]


def test_dependabot_exception_remains_scoped_per_changed_file() -> None:
    failures = check_contributor_scope(
        [
            ".github/workflows/code-scan.yml",
            ".github/dependabot.yml",
        ],
        "none",
        "dependabot[bot]",
        "dependabot/github_actions/actions/checkout-7.0.1",
    )

    assert [(failure.rule_id, failure.file) for failure in failures] == [
        ("POL-021", ".github/dependabot.yml"),
    ]
