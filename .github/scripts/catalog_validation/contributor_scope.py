"""Contributor authorization checks for trusted repository paths."""

from __future__ import annotations

from .findings import Failure


_MAINTAINER_PERMISSIONS = frozenset({"admin", "maintain", "write"})
_PUBLIC_CATALOG_ROOTS = frozenset({"agents", "starter-kits"})
_PROTECTED_ROOTS = frozenset({".auto-registry", ".github", ".vscode"})
_PROTECTED_PATHS = frozenset({"docs/validation-rules.md"})
_REGISTRY_REFRESH_BOT_AUTHORS = frozenset({
    "github-actions[bot]",
    "discovery-registry-bot[bot]",
})


def is_trusted_registry_refresh(author: str, head_ref: str) -> bool:
    return (
        head_ref.startswith("chore/registry-refresh")
        and author in _REGISTRY_REFRESH_BOT_AUTHORS
    )


def _is_public_contribution_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return False

    if normalized in _PROTECTED_PATHS or parts[0] in _PROTECTED_ROOTS:
        return False
    if len(parts) >= 2 and parts[:2] == ["docs", "schemas"]:
        return False

    if len(parts) >= 2 and parts[0] in _PUBLIC_CATALOG_ROOTS:
        return True
    if len(parts) >= 2 and parts[0] == "docs":
        return True
    if len(parts) >= 3 and parts[:2] == ["includes", "media"]:
        return True

    return normalized.lower().endswith(".md")


def check_contributor_scope(
    changed_files: list[str],
    author_permission: str | None,
    author: str = "",
    head_ref: str = "",
) -> list[Failure]:
    """Protect trusted code and configuration from non-maintainer PRs."""
    if author_permission is None:
        return []

    permission = author_permission.strip().lower() or "unknown"
    if (
        permission in _MAINTAINER_PERMISSIONS
        or is_trusted_registry_refresh(author, head_ref)
    ):
        return []

    actor = f"@{author}" if author else "The PR author"
    failures: list[Failure] = []
    for changed_file in changed_files:
        if not _is_public_contribution_path(changed_file):
            failures.append(Failure(
                "POL-021",
                changed_file,
                f"{actor} has repository permission '{permission}'. Public contributors "
                "may modify catalog content and documentation, but trusted automation, "
                "repository configuration, schemas, generated output, and executable "
                "utilities require a maintainer-authored change. Remove this file from "
                "the PR or ask a repository maintainer to author the change.",
            ))
    return failures