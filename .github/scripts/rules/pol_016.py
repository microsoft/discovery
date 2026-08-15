#!/usr/bin/env python3
"""
POL-016 — a file named like an image must actually be that image.

Extensions are a claim, not a fact. This rule verifies the claim, which matters
in two directions:

* A mislabelled raster file (``diagram.png`` holding a ZIP, an ELF, or a JPEG)
  is either a mistake or an attempt to get past a reviewer who trusts the name.
* SVG is the one image format accepted as source, because it is text — and
  therefore the one that can carry executable content.

Applies to ``agents/`` and ``starter-kits/`` — the trees open to public
contribution, and the only ones this policy governs.
"""

from __future__ import annotations

from pathlib import Path

from image_inspector import inspect
from rules.base import Finding, Rule, RuleContext, Scope, Severity

GUARDED_PREFIXES = ("agents/", "starter-kits/")


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []

    for rel in ctx.existing_changed_files():
        if not rel.startswith(GUARDED_PREFIXES):
            continue

        verdict = inspect(ctx.abs(rel))
        if verdict is None or verdict.ok:
            continue

        findings.append(Finding(
            rule_id="POL-016",
            file=rel,
            message=f"'{Path(rel).name}': {verdict.reason}",
        ))

    return findings


RULE = Rule(
    id="POL-016",
    summary="Image files under agents/ or starter-kits/ must contain the format their name claims, and SVGs must be free of active content.",
    scope=Scope.CHANGED_FILES,
    severity=Severity.ERROR,
    remediation=(
        "Re-export the image in its declared format, or rename it to match "
        "what it actually contains. For SVG, remove scripts, event handler "
        "attributes, javascript: URIs, entity declarations, embedded documents, "
        "and remote references — the catalog accepts declarative artwork only."
    ),
    docs="docs/authoring-guides/agent-authoring-guide.md#images",
    tags=("security", "integrity"),
    check=check,
)
