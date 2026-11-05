"""Contributor authorization checks for trusted repository paths."""

from __future__ import annotations

from .findings import Failure


_MAINTAINER_PERMISSIONS = frozenset({"admin", "maintain", "write"})
_MICROSOFT_ORG_ASSOCIATIONS = frozenset({"member", "owner"})
_PUBLIC_CONTENT_ROOTS = frozenset({"agents", "starter-kits", "skills"})
_PROTECTED_ROOTS = frozenset({".auto-registry", ".github", ".vscode", "utilities"})
_PROTECTED_PATHS = frozenset({"docs/validation-rules.md"})
_PUBLIC_ROOT_FILES = frozenset({".gitignore"})
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
_DEPENDABOT_PIP_PATHS = frozenset({
    ".github/requirements-ci.txt",
    "agents/gwp-predictor/training/requirements.txt",
    "agents/zinc/tools/zinc/requirements.txt",
})
_DEPENDABOT_UV_PATHS = frozenset({
    "utilities/supercomputer-cli/discovery/pyproject.toml",
    "utilities/supercomputer-cli/discovery/uv.lock",
})


def is_trusted_registry_refresh(author: str, head_ref: str) -> bool:
    return (
        head_ref.startswith("chore/registry-refresh")
        and author in _REGISTRY_REFRESH_BOT_AUTHORS
    )


def is_trusted_dependabot_update(path: str, author: str, head_ref: str) -> bool:
    """Allow configured manifests changed by the real Dependabot App."""
    if author != _DEPENDABOT_AUTHOR:
        return False

    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    if head_ref.startswith("dependabot/github_actions/"):
        return (
            len(parts) == 3
            and parts[:2] == [".github", "workflows"]
            and _suffix(parts[-1]) in {".yml", ".yaml"}
        )
    if head_ref.startswith("dependabot/nuget/"):
        return normalized == ".config/dotnet-tools.json"
    if head_ref.startswith("dependabot/pip/"):
        return normalized in _DEPENDABOT_PIP_PATHS
    if head_ref.startswith("dependabot/uv/"):
        return normalized in _DEPENDABOT_UV_PATHS
    return False


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

    if normalized in _PUBLIC_ROOT_FILES:
        return True
    if len(parts) >= 2 and parts[0] in _PUBLIC_CONTENT_ROOTS:
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
    author_association: str = "",
) -> list[Failure]:
    """Protect trusted code and configuration from non-maintainer PRs."""
    if author_permission is None:
        return []

    permission = author_permission.strip().lower() or "unknown"
    association = author_association.strip().lower()
    if (
        permission in _MAINTAINER_PERMISSIONS
        or association in _MICROSOFT_ORG_ASSOCIATIONS
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
                f"{actor} has no visible trust signal for this protected path "
                f"(repository permission '{permission}', PR author association "
                f"'{association or 'none'}'). Public contributors may modify catalog "
                "content (agents/, starter-kits/, and skills/), documentation, and "
                "the root .gitignore. Utilities and other protected paths require "
                "repository write/maintain/admin permission or a visible "
                "Microsoft MEMBER/OWNER association. An absent association does not "
                "prove non-membership. Remove this file from the PR or ask a repository "
                "maintainer to help with the protected-path change. Correctness "
                "validation and normal GitHub CODEOWNER review protections still apply.",
            ))
    return failures
