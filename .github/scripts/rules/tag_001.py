#!/usr/bin/env python3
"""
TAG-001 — declared tags must come from the controlled vocabulary.

Tags are the catalog's discovery surface. Free text degrades it fast:
``protein-structure``, ``protein_structures``, and ``ProteinStructure`` mean the
same thing to a researcher and nothing to each other in a search index. So the
vocabulary lives in ``.github/policy/tag-taxonomy.yaml`` and grows by review.
"""

from __future__ import annotations

import difflib

from rules.base import Finding, Rule, RuleContext, Scope, Severity


def check(ctx: RuleContext) -> list[Finding]:
    folder = ctx.folder
    if folder is None:
        return []

    meta_rel = f"{folder.as_posix()}/metadata.yaml"
    if not ctx.abs(meta_rel).is_file():
        return []

    data, err = ctx.load_yaml(meta_rel)
    if err or not isinstance(data, dict):
        return []  # SCH-001 reports parse failures.

    vocabulary = ctx.policy.domain_tags
    if not vocabulary:
        return []  # No taxonomy configured; nothing to enforce against.

    findings: list[Finding] = []
    for tag in data.get("tags") or []:
        tag_str = str(tag)
        if tag_str.lower() in vocabulary:
            continue
        if any(tag_str.lower().startswith(p) for p in ctx.policy.reserved_tag_prefixes):
            continue  # TAG-002 owns reserved-namespace violations.

        suggestions = difflib.get_close_matches(tag_str.lower(), sorted(vocabulary), n=3, cutoff=0.6)
        hint = (
            f" Did you mean {', '.join(repr(s) for s in suggestions)}?"
            if suggestions else ""
        )
        findings.append(Finding(
            rule_id="TAG-001",
            file=meta_rel,
            message=(
                f"Tag '{tag_str}' is not in the catalog tag vocabulary.{hint} "
                f"Reuse an existing tag from '.github/policy/tag-taxonomy.yaml' "
                f"where one fits — near-synonyms fragment search results. If the "
                f"concept is genuinely new, add it to the taxonomy in a separate "
                f"CODEOWNERS-reviewed PR."
            ),
        ))

    return findings


RULE = Rule(
    id="TAG-001",
    summary="Tags declared in metadata.yaml must exist in the controlled tag vocabulary.",
    scope=Scope.AGENT_FOLDER,
    severity=Severity.ERROR,
    remediation=(
        "Use an existing tag from .github/policy/tag-taxonomy.yaml, or propose "
        "the new tag in a separate PR against that file."
    ),
    docs="docs/authoring-guides/agent-authoring-guide.md#tags",
    tags=("discoverability",),
    check=check,
)
