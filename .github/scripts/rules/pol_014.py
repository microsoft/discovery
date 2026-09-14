#!/usr/bin/env python3
"""
POL-014 — container base images must come from an approved source.

The base image is the largest piece of software in a contributed build and the
piece no reviewer reads. Restricting it to Docker Official Images, Microsoft's
registry, and a short reviewed list of publisher namespaces means every image
in the catalog traces back to a maintained, scannable upstream.

This rule intentionally does NOT require digest pinning, a non-root ``USER``,
or forbid piping installers into a shell. Those obstruct scientific images that
compile from source, and the allowlist plus weekly Docker Scout scanning
addresses supply-chain risk more directly than build-time nitpicking would.
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
            assert image is not None  # external_images filters these out

            # `{acr}.azurecr.io/...` is rewritten by the deployer to the target
            # subscription's own registry, so it is not a third-party base image.
            if image.is_deployer_placeholder:
                continue

            if ctx.policy.is_approved_base_image(
                image.registry, image.namespace_ref, image.is_docker_official
            ):
                continue

            findings.append(Finding(
                rule_id="POL-014",
                file=rel,
                line=directive.line,
                message=(
                    f"Base image '{image.raw}' comes from '{image.namespace_ref}', "
                    f"which is not an approved source. Use a Docker Official Image "
                    f"(for example 'python:3.12-slim', 'ubuntu:24.04', 'debian:12-slim'), "
                    f"an mcr.microsoft.com image, or one of the publisher namespaces "
                    f"listed in '.github/policy/base-images.yaml'. If this publisher "
                    f"is genuinely required, propose it in a separate PR against that "
                    f"file explaining why no official equivalent exists."
                ),
            ))

    return findings


RULE = Rule(
    id="POL-014",
    summary="Dockerfile base images must be Docker Official Images or come from an approved registry or publisher namespace.",
    scope=Scope.CHANGED_FILES,
    severity=Severity.ERROR,
    remediation=(
        "Switch the FROM line to a Docker Official Image, an mcr.microsoft.com "
        "image, or an approved publisher namespace from "
        ".github/policy/base-images.yaml."
    ),
    docs="docs/authoring-guides/agent-authoring-guide.md#base-images",
    tags=("security", "supply-chain"),
    check=check,
)
