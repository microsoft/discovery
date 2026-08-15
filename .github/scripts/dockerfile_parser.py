#!/usr/bin/env python3
"""
dockerfile_parser.py — minimal, dependency-free Dockerfile reading.

Only the parts the catalog policy cares about: which base images a Dockerfile
pulls, and where each reference sits so a finding can point at the right line.

Deliberately not a full Dockerfile parser. It resolves ``FROM ... AS name``
stage aliases so a multi-stage build's internal references are not mistaken for
external images, and it understands ``ARG``-substituted tags well enough to know
when a tag is indeterminate rather than guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: FROM [--platform=...] <image> [AS <stage>]
_FROM_RE = re.compile(
    r"^\s*FROM\s+(?:--\S+\s+)*(?P<ref>\S+)(?:\s+AS\s+(?P<alias>\S+))?",
    re.IGNORECASE,
)
_ARG_RE = re.compile(r"^\s*ARG\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:=(?P<default>\S*))?", re.IGNORECASE)
_VAR_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")

#: Docker Official Images live in the implicit `library` namespace.
DOCKER_OFFICIAL_NAMESPACE = "library"
DEFAULT_REGISTRY = "docker.io"


@dataclass(frozen=True)
class ImageRef:
    """A parsed image reference."""

    raw: str
    registry: str
    namespace: str
    repository: str
    tag: str | None
    digest: str | None

    @property
    def is_docker_official(self) -> bool:
        return self.registry == DEFAULT_REGISTRY and self.namespace == DOCKER_OFFICIAL_NAMESPACE

    @property
    def namespace_ref(self) -> str:
        return f"{self.registry}/{self.namespace}"

    @property
    def tag_is_variable(self) -> bool:
        return bool(self.tag and _VAR_RE.search(self.tag))

    @property
    def is_deployer_placeholder(self) -> bool:
        """True for refs like ``{acr}.azurecr.io/...`` that the Discovery deployer
        rewrites to the target subscription's own registry at build time."""
        return "{" in self.registry


@dataclass(frozen=True)
class FromDirective:
    line: int
    raw: str
    alias: str | None
    #: True when this FROM refers to an earlier stage in the same file.
    is_stage_reference: bool
    image: ImageRef | None


def parse_image_ref(ref: str) -> ImageRef:
    """Split an image reference into registry / namespace / repo / tag / digest."""
    remainder, digest = (ref.split("@", 1) + [None])[:2] if "@" in ref else (ref, None)

    parts = remainder.split("/")
    # A leading component is a registry only when it looks like a host: it
    # contains a dot or a colon, or is exactly "localhost".
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry, rest = parts[0], parts[1:]
    else:
        registry, rest = DEFAULT_REGISTRY, parts

    if len(rest) == 1:
        namespace, repo_and_tag = DOCKER_OFFICIAL_NAMESPACE, rest[0]
    else:
        namespace, repo_and_tag = rest[0], "/".join(rest[1:])

    if ":" in repo_and_tag:
        repository, tag = repo_and_tag.rsplit(":", 1)
    else:
        repository, tag = repo_and_tag, None

    return ImageRef(
        raw=ref,
        registry=registry,
        namespace=namespace,
        repository=repository,
        tag=tag,
        digest=digest,
    )


def parse_from_directives(text: str) -> list[FromDirective]:
    """Return every FROM in the file, with stage references marked."""
    args: dict[str, str] = {}
    aliases: set[str] = set()
    directives: list[FromDirective] = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        arg_match = _ARG_RE.match(line)
        if arg_match and arg_match.group("default") is not None:
            args[arg_match.group("name")] = arg_match.group("default")
            continue

        match = _FROM_RE.match(line)
        if not match:
            continue

        ref = match.group("ref")
        alias = match.group("alias")

        # Substitute ARG defaults so a pinned-by-variable tag resolves.
        resolved = _VAR_RE.sub(lambda m: args.get(m.group(1), m.group(0)), ref)

        is_stage = resolved.lower() in aliases or ref.lower() in aliases
        directives.append(FromDirective(
            line=lineno,
            raw=ref,
            alias=alias,
            is_stage_reference=is_stage,
            image=None if is_stage else parse_image_ref(resolved),
        ))

        if alias:
            aliases.add(alias.lower())

    return directives


def external_images(text: str) -> list[FromDirective]:
    """FROM directives that pull an image from a registry."""
    return [d for d in parse_from_directives(text) if not d.is_stage_reference and d.image]
