#!/usr/bin/env python3
"""
POL-016 — documentation images must be genuine, safe, small, and referenced.

Extensions are a claim, not a fact. This rule verifies the claim, which matters
in two directions:

* A mislabelled raster file (``diagram.png`` holding a ZIP, an ELF, or a JPEG)
  is either a mistake or an attempt to get past a reviewer who trusts the name.
* SVG can carry executable or remote content despite being rendered as an
    image, so only inert declarative SVG is accepted.
* Unreferenced or oversized assets add repository weight without contributing
    to the rendered documentation.

Applies to ``agents/`` and ``starter-kits/`` — the trees open to public
contribution, and the only ones this policy governs.
"""

from __future__ import annotations

from pathlib import Path

from image_inspector import (
    MARKDOWN_IMAGE_EXTENSIONS,
    MAX_MARKDOWN_IMAGE_BYTES,
    inspect,
    is_referenced_by_markdown,
)
from rules.base import Finding, Rule, RuleContext, Scope, Severity

GUARDED_PREFIXES = ("agents/", "starter-kits/")


def _owner_dir(ctx: RuleContext, rel: str) -> Path:
    parts = Path(rel.replace("\\", "/")).parts
    return ctx.repo.joinpath(*parts[:2])


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []

    for rel in ctx.existing_changed_files():
        if not rel.startswith(GUARDED_PREFIXES):
            continue

        image_path = ctx.abs(rel)
        verdict = inspect(image_path)
        if verdict is None:
            continue

        if not verdict.ok:
            findings.append(Finding(
                rule_id="POL-016",
                file=rel,
                message=f"'{Path(rel).name}': {verdict.reason}",
            ))
            continue

        suffix = Path(rel).suffix.lower()
        if suffix not in MARKDOWN_IMAGE_EXTENSIONS:
            findings.append(Finding(
                rule_id="POL-016",
                file=rel,
                message=(
                    f"'{Path(rel).name}' uses {suffix or 'no extension'}, which "
                    "is not an approved Markdown image format. Use PNG, JPEG, "
                    "GIF, WebP, or an inert SVG."
                ),
            ))
            continue

        size = image_path.stat().st_size
        if size > MAX_MARKDOWN_IMAGE_BYTES:
            findings.append(Finding(
                rule_id="POL-016",
                file=rel,
                message=(
                    f"'{Path(rel).name}' is {size} bytes; Markdown images must "
                    f"not exceed {MAX_MARKDOWN_IMAGE_BYTES} bytes (1 MiB). "
                    "Compress or resize it, or host it externally."
                ),
            ))
            continue

        if is_referenced_by_markdown(image_path, _owner_dir(ctx, rel)):
            continue

        findings.append(Finding(
            rule_id="POL-016",
            file=rel,
            message=(
                f"'{Path(rel).name}' is not embedded by Markdown within its "
                "agent or starter-kit folder. Remove this orphaned asset or "
                "reference it with Markdown image syntax."
            ),
        ))

    return findings


RULE = Rule(
    id="POL-016",
    summary="Images under agents/ or starter-kits/ must be safe Markdown formats, at most 1 MiB, and referenced by Markdown in the same catalog item.",
    scope=Scope.CHANGED_FILES,
    severity=Severity.ERROR,
    remediation=(
        "Use PNG, JPEG, GIF, WebP, or SVG; keep the file at or below 1 MiB; "
        "and embed it from Markdown in the same agent or starter-kit folder. "
        "Re-export the image if its content does not match its extension. For "
        "SVG, remove scripts, event handler "
        "attributes, javascript: URIs, entity declarations, embedded documents, "
        "and remote references — the catalog accepts declarative artwork only."
    ),
    docs="docs/authoring-guides/agent-authoring-guide.md#images",
    tags=("security", "integrity"),
    check=check,
)
