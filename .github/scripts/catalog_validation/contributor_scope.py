"""Contributor authorization checks for trusted repository paths."""

from __future__ import annotations

from .findings import Failure


_MAINTAINER_PERMISSIONS = frozenset({"admin", "maintain", "write"})
_PUBLIC_CATALOG_ROOTS = frozenset({"agents", "starter-kits"})
_PROTECTED_ROOTS = frozenset({".auto-registry", ".github", ".vscode"})
_PROTECTED_PATHS = frozenset({"docs/validation-rules.md"})
_PUBLIC_ROOT_DOCS = frozenset({"readme.md", "contributing.md"})
_DOC_SUFFIXES = (".md", ".markdown")
_EXECUTABLE_SUFFIXES = frozenset({
    ".sh", ".bash", ".zsh", ".ps1", ".psm1", ".psd1", ".bat", ".cmd",
    ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".php",
    ".bicep", ".tf", ".tfvars", ".hcl",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".com",
})
_REGISTRY_REFRESH_BOT_AUTHORS = frozenset({
    "github-actions[bot]",
    "discovery-registry-bot[bot]",
})
_DEPENDABOT_AUTHOR = "dependabot[bot]"
_DEPENDABOT_PROTECTED_PATHS = {
    "dependabot/pip/dot-github/": frozenset({
        ".github/requirements-ci.txt",
    }),
    "dependabot/nuget/dot-config/": frozenset({
        ".config/dotnet-tools.json",
    }),
}


def is_trusted_registry_refresh(author: str, head_ref: str) -> bool:
    return (
        head_ref.startswith("chore/registry-refresh")
        and author in _REGISTRY_REFRESH_BOT_AUTHORS
    )


def is_trusted_dependabot_update(path: str, author: str, head_ref: str) -> bool:
    """Allow only configured Dependabot manifests on matching bot branches."""
    if author != _DEPENDABOT_AUTHOR:
        return False

    normalized = path.replace("\\", "/")
    for ref_prefix, allowed_paths in _DEPENDABOT_PROTECTED_PATHS.items():
        if head_ref.startswith(ref_prefix):
            return normalized in allowed_paths

    if not head_ref.startswith("dependabot/github_actions/"):
        return False

    parts = normalized.split("/")
    return (
        len(parts) == 3
        and parts[:2] == [".github", "workflows"]
        and _suffix(parts[-1]) in {".yml", ".yaml"}
    )


def _suffix(name: str) -> str:
    base = name.lower()
    dot = base.rfind(".")
    return base[dot:] if dot > 0 else ""


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
        return _suffix(parts[-1]) not in _EXECUTABLE_SUFFIXES
    if len(parts) >= 3 and parts[:2] == ["includes", "media"]:
        return _suffix(parts[-1]) not in _EXECUTABLE_SUFFIXES

    name = parts[-1].lower()
    if name.endswith(_DOC_SUFFIXES):
        return len(parts) > 1 or name in _PUBLIC_ROOT_DOCS

    return False


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
        if is_trusted_dependabot_update(changed_file, author, head_ref):
            continue
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
