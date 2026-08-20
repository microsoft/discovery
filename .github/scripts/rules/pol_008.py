#!/usr/bin/env python3
"""
POL-008 — no binaries in agents/ or starter-kits/, decided by content.

The previous implementation compared file extensions against a denylist, which
a contributor defeats by renaming ``payload.so`` to ``notes.txt``. This rule
uses the file/libmagic database instead, so the check covers broadly recognized
formats regardless of what the file is called.

Model-weight formats are exempt here and validated by POL-009 instead (LFS
tracking, size cap, header validation, picklescan).
"""

from __future__ import annotations

from pathlib import Path

from content_sniffer import classify
from rules.base import Finding, Rule, RuleContext, Scope, Severity

#: Only these trees accept contributions; everything else is out of scope.
GUARDED_PREFIXES = ("agents/", "starter-kits/")


def _is_guarded(rel: str) -> bool:
    return rel.startswith(GUARDED_PREFIXES)


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []

    for rel in ctx.existing_changed_files():
        if not _is_guarded(rel):
            continue

        suffix = Path(rel).suffix.lower()
        if suffix in ctx.policy.model_weight_extensions:
            continue  # POL-009 owns these.

        result = classify(ctx.abs(rel))
        if not result.is_binary:
            continue
        if result.format == "unknown-binary":
            continue  # POL-020 owns malformed UTF-8 and unsafe text controls.

        if result.spoofed:
            message = (
                f"'{Path(rel).name}' is a binary file disguised with a text "
                f"extension. {result.detail} Only source code may be "
                f"contributed to {GUARDED_PREFIXES[0]} and "
                f"{GUARDED_PREFIXES[1]}. Remove the file; build artifacts "
                f"belong in the container image, and large assets belong in "
                f"external storage referenced from the Dockerfile."
            )
        else:
            message = (
                f"'{Path(rel).name}' is a binary file. {result.detail} "
                f"This repository accepts source code only. Remove the file; "
                f"build artifacts belong in the container image, and large "
                f"assets belong in external storage referenced from the "
                f"Dockerfile."
            )

        findings.append(Finding(rule_id="POL-008", file=rel, message=message))

    return findings


RULE = Rule(
    id="POL-008",
    summary="Files under agents/ and starter-kits/ must be source code, verified by content inspection.",
    scope=Scope.CHANGED_FILES,
    severity=Severity.ERROR,
    remediation=(
        "Remove the binary from the PR. Compile or download it inside the "
        "tool's Dockerfile, or host it externally and reference it by URL. "
        "Model weights are the only exception and must satisfy POL-009."
    ),
    docs="docs/authoring-guides/agent-authoring-guide.md#no-binaries",
    tags=("security", "supply-chain"),
    check=check,
)
