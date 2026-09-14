#!/usr/bin/env python3
"""
POL-017 — base image tags should not float.

``FROM condaforge/mambaforge:latest`` builds a different image every week. That
breaks reproducibility of published scientific results and means a vulnerability
scan run on Monday says nothing about Friday's build.

Reported as a warning, not an error: eleven existing FROM lines float, and
forcing them all to pin in one change would be disruptive without being urgent.
The signal stays visible in PR output and in the weekly report.
"""

from __future__ import annotations

from dockerfile_parser import external_images
from rules.base import Finding, Rule, RuleContext, Scope, Severity

GUARDED_PREFIXES = ("agents/", "starter-kits/")


def _is_dockerfile(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".Dockerfile")


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []

    for rel in ctx.existing_changed_files():
        if not rel.startswith(GUARDED_PREFIXES) or not _is_dockerfile(rel):
            continue

        text = ctx.read_text(rel)
        if text is None:
            continue

        for directive in external_images(text):
            image = directive.image
            assert image is not None

            if image.digest or image.is_deployer_placeholder:
                continue
            # An unresolved ARG could hold anything; the author has at least
            # made the version a deliberate build input.
            if image.tag_is_variable:
                continue

            tag = image.tag
            if tag is None:
                findings.append(Finding(
                    rule_id="POL-017",
                    file=rel,
                    line=directive.line,
                    message=(
                        f"Base image '{image.raw}' has no tag, so it resolves to "
                        f"':latest' and changes without notice. Pin an explicit version."
                    ),
                ))
            elif tag.lower() in ctx.policy.floating_tags:
                findings.append(Finding(
                    rule_id="POL-017",
                    file=rel,
                    line=directive.line,
                    message=(
                        f"Base image '{image.raw}' uses the floating tag "
                        f"'{tag}'. The image rebuilds upstream without notice, so "
                        f"results are not reproducible and a vulnerability scan "
                        f"only describes the build that ran at scan time. Pin an "
                        f"explicit version, for example "
                        f"'{image.namespace_ref.split('/')[-1]}/{image.repository}:<version>'."
                    ),
                ))

    return findings


RULE = Rule(
    id="POL-017",
    summary="Base image tags should be pinned to an explicit version rather than a floating tag such as :latest.",
    scope=Scope.CHANGED_FILES,
    severity=Severity.WARNING,
    remediation=(
        "Replace the floating tag with an explicit version, or supply it through "
        "an ARG with a pinned default so the version is a visible build input."
    ),
    docs="docs/authoring-guides/agent-authoring-guide.md#base-images",
    tags=("supply-chain", "reproducibility"),
    check=check,
)
