#!/usr/bin/env python3
"""POL-018 — catalog webpage URLs must resolve to real public HTML pages."""

from __future__ import annotations

import json

from contact_network_validator import ContactNetworkPolicy, validate_webpage
from rules.base import Finding, Rule, RuleContext, Scope
from source_locations import line_for_key_path

POLICY_PATH = ".github/policy/contact-network.json"


def _targets(ctx: RuleContext) -> list[tuple[str, str, str, int]]:
    targets: list[tuple[str, str, str, int]] = []

    for folder in sorted(ctx.agent_folders):
        rel = (folder / "metadata.yaml").as_posix()
        data, error = ctx.load_yaml(rel)
        if error or not isinstance(data, dict):
            continue
        publisher = data.get("publisher") or {}
        if not isinstance(publisher, dict):
            continue
        value = publisher.get("support_url")
        if isinstance(value, str) and value:
            line = line_for_key_path(ctx.read_text(rel) or "", ("publisher", "support_url"))
            targets.append((rel, "publisher.support_url", value, line))

    for folder in sorted(ctx.kit_folders):
        rel = (folder / "kit.json").as_posix()
        data, error = ctx.load_json(rel)
        if error or not isinstance(data, dict):
            continue

        author = data.get("author") or {}
        if isinstance(author, dict):
            value = author.get("url")
            if isinstance(value, str) and value:
                line = line_for_key_path(ctx.read_text(rel) or "", ("author", "url"))
                targets.append((rel, "author.url", value, line))

        for key in ("homepage", "repository"):
            value = data.get(key)
            if isinstance(value, str) and value:
                line = line_for_key_path(ctx.read_text(rel) or "", (key,))
                targets.append((rel, key, value, line))

    return targets


def check(ctx: RuleContext) -> list[Finding]:
    try:
        policy = ContactNetworkPolicy.load(ctx.abs(POLICY_PATH))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return [Finding(
            rule_id="POL-018",
            file=POLICY_PATH,
            message=f"Contact network policy could not be loaded: {exc}",
        )]

    findings: list[Finding] = []
    checked: dict[str, str | None] = {}
    for rel, field, value, line in _targets(ctx):
        if value not in checked:
            checked[value] = validate_webpage(value, policy.webpage)
        error = checked[value]
        if error:
            findings.append(Finding(
                rule_id="POL-018",
                file=rel,
                line=line,
                message=f"'{field}' must identify a real public HTML webpage: {error}.",
            ))
    return findings


RULE = Rule(
    id="POL-018",
    summary="Catalog webpage URLs must resolve to reachable public HTML pages.",
    scope=Scope.REPO,
    remediation=(
        "Use an HTTPS URL on port 443 that resolves only to public addresses, "
        "follows at most five public HTTPS redirects, and returns a non-empty "
        "HTML or XHTML response with a successful HTTP status."
    ),
    docs="docs/authoring-guides/agent-authoring-guide.md#metadata-reference",
    tags=("network", "publisher", "ssrf"),
    check=check,
)