#!/usr/bin/env python3
"""POL-022 — catalog container builds must use Docker-compatible filenames."""

from __future__ import annotations

import re
from pathlib import Path

from rules.base import Finding, Rule, RuleContext, Scope, Severity


GUARDED_PREFIXES = ("agents/", "starter-kits/")
_CPP_DIRECTIVE_RE = re.compile(
    r"^\s*#\s*(?:include|define|if|ifdef|ifndef|elif|else|endif|undef|"
    r"pragma|error|line)\b"
)


def _is_containerfile_name(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered == "containerfile"
        or lowered.startswith("containerfile.")
        or lowered.endswith(".containerfile")
        or ".containerfile." in lowered
    )


def _is_preprocessed_dockerfile(name: str) -> bool:
    lowered = name.lower()
    if not lowered.endswith(".in"):
        return False
    without_in = lowered[:-3]
    return (
        without_in == "dockerfile"
        or without_in.startswith("dockerfile.")
        or without_in.endswith(".dockerfile")
        or ".dockerfile." in without_in
    )


def _preprocessor_line(text: str | None) -> int:
    if text is None:
        return 1
    for line_number, line in enumerate(text.splitlines(), start=1):
        if _CPP_DIRECTIVE_RE.match(line):
            return line_number
    return 1


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []

    for rel in ctx.existing_changed_files():
        normalized = rel.replace("\\", "/")
        if not normalized.startswith(GUARDED_PREFIXES):
            continue

        name = Path(normalized).name
        is_containerfile = _is_containerfile_name(name)
        is_preprocessed = (
            name.lower().endswith(".in")
            and (is_containerfile or _is_preprocessed_dockerfile(name))
        )
        if not is_containerfile and not is_preprocessed:
            continue

        destination = str(Path(normalized).with_name("Dockerfile")).replace("\\", "/")
        if is_preprocessed:
            line = _preprocessor_line(ctx.read_text(rel))
            message = (
                f"'{name}' uses Podman's .in preprocessing convention, which Docker "
                "does not apply to Dockerfiles. Resolve the C-preprocessor directives "
                f"and commit their single rendered result as '{destination}'. This "
                "migration is not safe to perform as a filename-only conversion. See "
                "docs/authoring-guides/podman-to-docker-migration.md or invoke the "
                "migrate-podman-containerfile skill for guided remediation."
            )
        else:
            line = 1
            message = (
                f"'{name}' is a Podman Containerfile name, but catalog tools require "
                f"the canonical Docker filename '{destination}'. Plain Containerfiles "
                "normally use Dockerfile syntax and can usually be renamed directly. "
                "See docs/authoring-guides/podman-to-docker-migration.md or invoke the "
                "migrate-podman-containerfile skill."
            )

        findings.append(Finding(
            rule_id="POL-022",
            file=normalized,
            line=line,
            message=message,
        ))

    return findings


RULE = Rule(
    id="POL-022",
    summary=(
        "Catalog container builds must use Docker-compatible Dockerfile names "
        "and must not rely on Podman .in preprocessing."
    ),
    scope=Scope.CHANGED_FILES,
    severity=Severity.ERROR,
    remediation=(
        "For a plain Containerfile, rename it to Dockerfile. For Containerfile.in "
        "or Dockerfile.in, resolve preprocessing first and commit one rendered "
        "Dockerfile. Use the migrate-podman-containerfile skill for a guarded "
        "migration."
    ),
    docs="docs/authoring-guides/podman-to-docker-migration.md",
    tags=("compatibility", "containers"),
    check=check,
)
