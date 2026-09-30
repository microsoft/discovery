#!/usr/bin/env python3
"""Classify trusted PR file metadata into narrowly scoped merge lanes."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any


_TRUSTED_ASSOCIATIONS = frozenset({"MEMBER", "OWNER"})
_MANIFEST_PATH = re.compile(
    r"^docs/discovery-app/releases/manifests/[a-z][a-z0-9-]*\.json$"
)
_TOOLBOX_ROOT = "utilities/discovery-toolbox/"
_TOOLBOX_DOCS = frozenset({
    f"{_TOOLBOX_ROOT}README.md",
    f"{_TOOLBOX_ROOT}PRIVACY.md",
})
_TOOLBOX_POINTER = f"{_TOOLBOX_ROOT}vsix/latest.json"
_TOOLBOX_VSIX = re.compile(
    r"^utilities/discovery-toolbox/vsix/"
    r"DiscoveryToolbox-v[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\.vsix$"
)
_DEPENDABOT_AUTHOR = "dependabot[bot]"
_DEPENDABOT_EXACT_SCOPES = {
    "dependabot/nuget/dot-config/": frozenset({
        ".config/dotnet-tools.json",
    }),
    "dependabot/pip/dot-github/": frozenset({
        ".github/requirements-ci.txt",
    }),
    "dependabot/pip/agents/gwp-predictor/training/": frozenset({
        "agents/gwp-predictor/training/requirements.txt",
    }),
    "dependabot/pip/agents/zinc/tools/zinc/": frozenset({
        "agents/zinc/tools/zinc/requirements.txt",
    }),
    "dependabot/uv/utilities/supercomputer-cli/discovery/": frozenset({
        "utilities/supercomputer-cli/discovery/pyproject.toml",
        "utilities/supercomputer-cli/discovery/uv.lock",
    }),
}
_DEPENDABOT_WORKFLOW = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")
_DEPENDABOT_DOCKERFILE = re.compile(
    r"^agents/[^/]+/tools/[^/]+/Dockerfile$"
)


def _is_dependabot_scope(
    paths: list[str],
    statuses: list[str],
    author: str,
    head_ref: str,
) -> bool:
    if (
        author != _DEPENDABOT_AUTHOR
        or not paths
        or any(status != "modified" for status in statuses)
    ):
        return False

    if head_ref.startswith("dependabot/github_actions/"):
        return all(_DEPENDABOT_WORKFLOW.fullmatch(path) for path in paths)

    for ref_prefix, allowed_paths in _DEPENDABOT_EXACT_SCOPES.items():
        if head_ref.startswith(ref_prefix):
            return set(paths) <= allowed_paths

    if not head_ref.startswith("dependabot/docker/"):
        return False
    if not all(_DEPENDABOT_DOCKERFILE.fullmatch(path) for path in paths):
        return False
    return all(
        head_ref.startswith(f"dependabot/docker/{path.rsplit('/', 1)[0]}/")
        for path in paths
    )


def classify(
    files: list[dict[str, Any]],
    author_association: str,
    author: str = "",
    head_ref: str = "",
) -> dict[str, Any]:
    trusted_author = author_association.upper() in _TRUSTED_ASSOCIATIONS
    paths = [str(item.get("filename", "")).replace("\\", "/") for item in files]
    statuses = [str(item.get("status", "")).lower() for item in files]

    manifest = (
        trusted_author
        and len(files) == 1
        and _MANIFEST_PATH.fullmatch(paths[0]) is not None
        and statuses[0] in {"added", "modified", "renamed"}
    )

    toolbox_paths_valid = all(
        path in _TOOLBOX_DOCS
        or path == _TOOLBOX_POINTER
        or _TOOLBOX_VSIX.fullmatch(path) is not None
        for path in paths
    )
    added_vsix = sum(
        1
        for path, status in zip(paths, statuses, strict=True)
        if _TOOLBOX_VSIX.fullmatch(path) is not None and status == "added"
    )
    toolbox = (
        trusted_author
        and 2 <= len(files) <= 5
        and toolbox_paths_valid
        and _TOOLBOX_POINTER in paths
        and added_vsix == 1
    )
    dependabot = _is_dependabot_scope(paths, statuses, author, head_ref)

    lane = "manifest-auto-approval" if manifest else (
        "toolbox-vsix-one-approval" if toolbox else (
            "dependabot-one-human-approval" if dependabot else "standard"
        )
    )
    return {
        "lane": lane,
        "manifest_auto_approval": manifest,
        "toolbox_one_approval": toolbox,
        "dependabot_one_human_approval": dependabot,
        "trusted_author": trusted_author,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files-json", required=True)
    parser.add_argument("--author-association", default="NONE")
    parser.add_argument("--author", default="")
    parser.add_argument("--head-ref", default="")
    parser.add_argument(
        "--eligible-for",
        choices=("manifest", "toolbox", "dependabot"),
        required=True,
    )
    args = parser.parse_args()

    with Path(args.files_json).open(encoding="utf-8") as stream:
        import json

        files = json.load(stream)
    if not isinstance(files, list):
        raise SystemExit("Pull request files payload must be a JSON array.")
    classification = classify(
        files,
        args.author_association,
        args.author,
        args.head_ref,
    )
    eligible_by_lane = {
        "manifest": classification["manifest_auto_approval"],
        "toolbox": classification["toolbox_one_approval"],
        "dependabot": classification["dependabot_one_human_approval"],
    }
    eligible = eligible_by_lane[args.eligible_for]
    raise SystemExit(0 if eligible else 1)


if __name__ == "__main__":
    main()
