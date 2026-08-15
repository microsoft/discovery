#!/usr/bin/env python3
"""
list_base_images.py — enumerate the container base images the catalog depends on.

Feeds the weekly deep scan: the set of distinct external base images across
every Dockerfile under ``agents/``, which the workflow then runs through Docker
Scout for CVE data. Deployer placeholders (``{acr}.azurecr.io/...``) and
multi-stage internal references are excluded — neither is an upstream image.

Usage:
    python .github/scripts/list_base_images.py                # human table
    python .github/scripts/list_base_images.py --json         # {"images": [...]}
    python .github/scripts/list_base_images.py --matrix       # GH Actions matrix
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from dockerfile_parser import external_images


def collect(repo: Path) -> dict[str, list[str]]:
    """Map each distinct base image to the Dockerfiles that use it."""
    usage: dict[str, list[str]] = defaultdict(list)

    for df in sorted((repo / "agents").rglob("Dockerfile*")):
        try:
            text = df.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for directive in external_images(text):
            image = directive.image
            if image is None or image.is_deployer_placeholder:
                continue
            if image.tag_is_variable:
                # The concrete tag is a build input; scanning a literal
                # "${VAR}" reference would just fail.
                continue
            rel = str(df.relative_to(repo)).replace("\\", "/")
            usage[image.raw].append(f"{rel}:{directive.line}")

    return dict(sorted(usage.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument("--matrix", action="store_true",
                        help="Emit a GitHub Actions matrix payload.")
    args = parser.parse_args()

    usage = collect(Path(args.repo_root).resolve())

    if args.matrix:
        # Actions caps matrix size at 256 entries; the catalog is far below that.
        print(json.dumps({"image": list(usage.keys())}))
        return 0

    if args.json:
        print(json.dumps(
            {"count": len(usage), "images": [
                {"image": img, "used_by": refs} for img, refs in usage.items()
            ]},
            indent=2,
        ))
        return 0

    print(f"{len(usage)} distinct base image(s) across the catalog:\n")
    for img, refs in usage.items():
        print(f"  {img}")
        print(f"      used by {len(refs)} Dockerfile(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
