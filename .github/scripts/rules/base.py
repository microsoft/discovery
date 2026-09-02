#!/usr/bin/env python3
"""
rules.base — core types for the modular rule engine.

Every rule lives in its own module under ``.github/scripts/rules/`` and exports
a single module-level ``RULE`` object. The registry discovers them by import,
so adding a rule means adding one file plus one test file — no edits to a
central dispatcher.

A rule declares *what it applies to* rather than iterating the repo itself.
The engine resolves the scope once and hands the rule a prepared context, which
keeps rules short and makes them trivial to unit test in isolation.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

import yaml


class Severity(str, Enum):
    """How the engine treats a finding.

    ERROR blocks the PR. WARNING is reported but does not block — used by the
    ratchet for pre-existing violations in legacy content.
    """

    ERROR = "error"
    WARNING = "warning"


class Scope(str, Enum):
    """What the engine iterates when invoking a rule."""

    #: Called once with every changed file in the PR.
    CHANGED_FILES = "changed-files"
    #: Called once per touched `agents/<name>/` folder.
    AGENT_FOLDER = "agent-folder"
    #: Called once per touched `starter-kits/<name>/` folder.
    KIT_FOLDER = "kit-folder"
    #: Called once for the whole repository.
    REPO = "repo"


@dataclass(frozen=True)
class Finding:
    """One rule violation at one location."""

    rule_id: str
    file: str
    message: str
    line: int = 1
    severity: Severity = Severity.ERROR

    def to_dict(self) -> dict:
        # Matches the JSON contract consumed by pr-review.yml's posting step.
        return {
            "rule_id": self.rule_id,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "severity": self.severity.value,
        }


@dataclass
class PolicyConfig:
    """Contents of `.github/policy/`, loaded once per run."""

    allowed_extensions: frozenset[str] = frozenset()
    allowed_filenames: frozenset[str] = frozenset()
    allowed_patterns: tuple[str, ...] = ()
    exempt_directories: frozenset[str] = frozenset()
    model_weight_extensions: frozenset[str] = frozenset()
    allow_docker_official_images: bool = True
    trusted_registries: frozenset[str] = frozenset()
    approved_namespaces: frozenset[str] = frozenset()
    floating_tags: frozenset[str] = frozenset()
    domain_tags: frozenset[str] = frozenset()
    reserved_tag_prefixes: tuple[str, ...] = ()
    computed_tags: frozenset[str] = frozenset()

    @classmethod
    def load(cls, repo: Path) -> "PolicyConfig":
        policy_dir = repo / ".github" / "policy"

        allowlist: dict = {}
        allowlist_path = policy_dir / "source-allowlist.yaml"
        if allowlist_path.exists():
            try:
                allowlist = yaml.safe_load(allowlist_path.read_text(encoding="utf-8")) or {}
            except (yaml.YAMLError, OSError):
                allowlist = {}

        base_images: dict = {}
        base_images_path = policy_dir / "base-images.yaml"
        if base_images_path.exists():
            try:
                base_images = yaml.safe_load(base_images_path.read_text(encoding="utf-8")) or {}
            except (yaml.YAMLError, OSError):
                base_images = {}

        taxonomy: dict = {}
        taxonomy_path = policy_dir / "tag-taxonomy.yaml"
        if taxonomy_path.exists():
            try:
                taxonomy = yaml.safe_load(taxonomy_path.read_text(encoding="utf-8")) or {}
            except (yaml.YAMLError, OSError):
                taxonomy = {}

        domain_tags: set[str] = set()
        for group in (taxonomy.get("domains") or {}).values():
            for tag in group or []:
                domain_tags.add(str(tag).lower())

        return cls(
            allowed_extensions=frozenset(
                str(e).lower() for e in allowlist.get("extensions", []) or []
            ),
            allowed_filenames=frozenset(
                str(f) for f in allowlist.get("filenames", []) or []
            ),
            allowed_patterns=tuple(str(p) for p in allowlist.get("patterns", []) or []),
            exempt_directories=frozenset(
                str(d).strip("/") for d in allowlist.get("exempt_directories", []) or []
            ),
            model_weight_extensions=frozenset(
                str(e).lower() for e in allowlist.get("model_weight_extensions", []) or []
            ),
            allow_docker_official_images=bool(
                base_images.get("allow_docker_official_images", True)
            ),
            trusted_registries=frozenset(
                str(r.get("host", "")).lower()
                for r in base_images.get("registries", []) or []
                if isinstance(r, dict) and r.get("host")
            ),
            approved_namespaces=frozenset(
                str(n.get("ref", "")).lower()
                for n in base_images.get("namespaces", []) or []
                if isinstance(n, dict) and n.get("ref")
            ),
            floating_tags=frozenset(
                str(t).lower() for t in base_images.get("floating_tags", []) or []
            ),
            domain_tags=frozenset(domain_tags),
            reserved_tag_prefixes=tuple(
                str(p).lower() for p in taxonomy.get("reserved_prefixes", []) or []
            ),
            computed_tags=frozenset(
                str(t).lower() for t in taxonomy.get("computed", []) or []
            ),
        )

    def is_approved_base_image(
        self, registry: str, namespace_ref: str, is_docker_official: bool
    ) -> bool:
        """True when a base image comes from an approved source."""
        if is_docker_official and self.allow_docker_official_images:
            return True
        if registry.lower() in self.trusted_registries:
            return True
        return namespace_ref.lower() in self.approved_namespaces

    def is_allowed_source_file(self, rel_path: str) -> bool:
        """True when the filename is permitted by the source allowlist.

        This is a readability control, not a security control — the content
        sniffer is what actually stops a renamed binary.
        """
        parts = Path(rel_path.replace("\\", "/")).parts
        if any(p in self.exempt_directories for p in parts[:-1]):
            return True
        name = parts[-1] if parts else rel_path
        if name in self.allowed_filenames:
            return True
        if Path(rel_path).suffix.lower() in self.allowed_extensions:
            return True
        return any(fnmatch.fnmatch(name, pat) for pat in self.allowed_patterns)


@dataclass
class RuleContext:
    """Everything a rule needs, prepared by the engine."""

    repo: Path
    changed_files: list[str]
    agent_folders: set[Path]
    kit_folders: set[Path]
    policy: PolicyConfig
    is_ci: bool = False
    #: Populated by the engine when iterating a folder scope.
    folder: Path | None = None

    def abs(self, rel: str | Path) -> Path:
        return self.repo / rel

    def rel(self, path: Path) -> str:
        return str(path.relative_to(self.repo)).replace("\\", "/")

    def read_text(self, rel: str | Path) -> str | None:
        try:
            return self.abs(rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def load_yaml(self, rel: str | Path) -> tuple[object | None, str | None]:
        path = self.abs(rel)
        try:
            return yaml.safe_load(path.read_text(encoding="utf-8")), None
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
            return None, str(e)

    def load_json(self, rel: str | Path) -> tuple[object | None, str | None]:
        path = self.abs(rel)
        try:
            return json.loads(path.read_text(encoding="utf-8")), None
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            return None, str(e)

    def changed_under(self, prefix: str) -> list[str]:
        norm = prefix.replace("\\", "/")
        return [f for f in self.changed_files if f.replace("\\", "/").startswith(norm)]

    def existing_changed_files(self) -> list[str]:
        """Changed files that still exist — i.e. additions and modifications.

        Deletions are excluded so that removing a forbidden file is always
        allowed; that is the remediation we want contributors to take.
        """
        return [f for f in self.changed_files if self.abs(f).is_file()]


@dataclass(frozen=True)
class Rule:
    """A single validation rule.

    Attributes:
        id:          Stable identifier, e.g. "POL-008". Appears in PR comments.
        summary:     One-line description, used to generate docs.
        severity:    Default severity; the ratchet may downgrade it.
        scope:       What the engine iterates when calling ``check``.
        remediation: Actionable fix instructions shown to the contributor.
        check:       The rule body.
        docs:        Optional link fragment for further reading.
    """

    id: str
    summary: str
    scope: Scope
    remediation: str
    check: Callable[[RuleContext], list[Finding]]
    severity: Severity = Severity.ERROR
    docs: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.id or not self.summary:
            raise ValueError("Rule requires a non-empty id and summary.")
