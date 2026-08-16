#!/usr/bin/env python3
"""POL-019 — catalog contact email domains must exist in public DNS."""

from __future__ import annotations

import json

from contact_network_validator import ContactNetworkPolicy, validate_email_domain
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
        value = publisher.get("contact")
        if isinstance(value, str) and value:
            line = line_for_key_path(ctx.read_text(rel) or "", ("publisher", "contact"))
            targets.append((rel, "publisher.contact", value, line))

    for folder in sorted(ctx.kit_folders):
        rel = (folder / "kit.json").as_posix()
        data, error = ctx.load_json(rel)
        if error or not isinstance(data, dict):
            continue
        author = data.get("author") or {}
        if not isinstance(author, dict):
            continue
        value = author.get("email")
        if isinstance(value, str) and value:
            line = line_for_key_path(ctx.read_text(rel) or "", ("author", "email"))
            targets.append((rel, "author.email", value, line))

    return targets


def check(ctx: RuleContext) -> list[Finding]:
    try:
        policy = ContactNetworkPolicy.load(ctx.abs(POLICY_PATH))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return [Finding(
            rule_id="POL-019",
            file=POLICY_PATH,
            message=f"Contact network policy could not be loaded: {exc}",
        )]

    findings: list[Finding] = []
    checked: dict[str, str | None] = {}
    for rel, field, value, line in _targets(ctx):
        cache_key = value.rsplit("@", 1)[-1].lower()
        if cache_key not in checked:
            checked[cache_key] = validate_email_domain(value, policy.email_domain)
        error = checked[cache_key]
        if error:
            findings.append(Finding(
                rule_id="POL-019",
                file=rel,
                line=line,
                message=f"'{field}' must use a real email domain: {error}.",
            ))
    return findings


RULE = Rule(
    id="POL-019",
    summary="Catalog contact email domains must exist and advertise usable mail DNS records.",
    scope=Scope.REPO,
    remediation=(
        "Use an address whose fully qualified domain publishes a non-null MX "
        "record, or an A/AAAA record permitted by implicit-MX fallback. This "
        "check validates the domain only; it does not prove mailbox ownership."
    ),
    docs="docs/authoring-guides/agent-authoring-guide.md#metadata-reference",
    tags=("network", "publisher", "email"),
    check=check,
)