#!/usr/bin/env python3
"""
POL-015 — added files must match the source allowlist.

POL-008 stops binaries by inspecting content. This rule is the complementary
readability control: it keeps the catalog to a known, reviewable set of file
types so an unexpected format has to be discussed in a PR against
`.github/policy/source-allowlist.yaml` rather than slipping in unnoticed.

It is deliberately extension-based and deliberately NOT the security boundary.
"""

from __future__ import annotations

from pathlib import Path

from rules.base import Finding, Rule, RuleContext, Scope, Severity

GUARDED_PREFIXES = ("agents/", "starter-kits/")


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []

    for rel in ctx.existing_changed_files():
        if not rel.startswith(GUARDED_PREFIXES):
            continue

        suffix = Path(rel).suffix.lower()
        if suffix in ctx.policy.model_weight_extensions:
            continue  # POL-009 owns these.

        if ctx.policy.is_allowed_source_file(rel):
            continue

        name = Path(rel).name
        findings.append(Finding(
            rule_id="POL-015",
            file=rel,
            message=(
                f"'{name}' is not an approved file type for the catalog. "
                f"Permitted extensions and filenames are listed in "
                f"'.github/policy/source-allowlist.yaml'. If this file type is "
                f"legitimately needed, open a PR adding it to the allowlist "
                f"(CODEOWNERS-gated) and explain the use case."
            ),
        ))

    return findings


RULE = Rule(
    id="POL-015",
    summary="Added files must use an approved extension or filename from the source allowlist.",
    scope=Scope.CHANGED_FILES,
    severity=Severity.ERROR,
    remediation=(
        "Rename the file to an approved type, remove it, or extend "
        ".github/policy/source-allowlist.yaml in a separate CODEOWNERS-reviewed PR."
    ),
    docs="docs/authoring-guides/agent-authoring-guide.md#approved-file-types",
    tags=("hygiene",),
    check=check,
)
