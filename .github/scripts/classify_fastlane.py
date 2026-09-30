#!/usr/bin/env python3
"""Classify trusted PR file metadata into narrowly scoped merge lanes."""

from __future__ import annotations

import argparse
import json
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


def classify(files: list[dict[str, Any]], author_association: str) -> dict[str, Any]:
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

    lane = "manifest-auto-approval" if manifest else (
        "toolbox-vsix-one-approval" if toolbox else "standard"
    )
    return {
        "lane": lane,
        "manifest_auto_approval": manifest,
        "toolbox_one_approval": toolbox,
        "trusted_author": trusted_author,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files-json", required=True)
    parser.add_argument("--author-association", default="NONE")
    args = parser.parse_args()

    with Path(args.files_json).open(encoding="utf-8") as stream:
        files = json.load(stream)
    if not isinstance(files, list):
        raise SystemExit("Pull request files payload must be a JSON array.")
    print(json.dumps(classify(files, args.author_association), separators=(",", ":")))


if __name__ == "__main__":
    main()
