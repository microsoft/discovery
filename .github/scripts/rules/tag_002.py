#!/usr/bin/env python3
"""
TAG-002 — the computed tag namespace is reserved for CI.

Tags such as ``auto:has-tests``, ``party:1p``, and ``tier:gold`` describe what
an agent verifiably contains. CI derives them from the repository. If an author
could declare them by hand, they would be claims rather than facts, and the
assurance tier they feed would mean nothing.
"""

from __future__ import annotations

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
        return []

    prefixes = ctx.policy.reserved_tag_prefixes
    if not prefixes:
        return []

    findings: list[Finding] = []
    for tag in data.get("tags") or []:
        tag_str = str(tag)
        matched = next((p for p in prefixes if tag_str.lower().startswith(p)), None)
        if matched is None:
            continue

        findings.append(Finding(
            rule_id="TAG-002",
            file=meta_rel,
            message=(
                f"Tag '{tag_str}' uses the reserved prefix '{matched}'. Tags in "
                f"that namespace are computed by CI from what the agent actually "
                f"contains and are published to .auto-registry/; declaring one by "
                f"hand asserts something the catalog is meant to verify. Remove it "
                f"— if the agent qualifies, the tag will be applied automatically."
            ),
        ))

    return findings


RULE = Rule(
    id="TAG-002",
    summary="Authors must not declare tags in the CI-computed namespaces (auto:, tier:, party:, capability:).",
    scope=Scope.AGENT_FOLDER,
    severity=Severity.ERROR,
    remediation=(
        "Remove the reserved-prefix tag from metadata.yaml. CI applies these "
        "automatically based on the agent's contents."
    ),
    docs="docs/authoring-guides/agent-authoring-guide.md#tags",
    tags=("integrity", "discoverability"),
    check=check,
)
