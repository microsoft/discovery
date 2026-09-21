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
    #: (rel_path, message) for every policy problem found at load time —
    #: a missing/empty/malformed required file, or a field of the wrong
    #: shape. A non-empty tuple means one or more checks would otherwise run
    #: with empty or coerced configuration; the runner turns these into
    #: blocking failures rather than letting a policy fail open.
    config_errors: tuple[tuple[str, str], ...] = ()

    #: Policy files that are security controls. A missing, empty, or malformed
    #: one must fail the run — never silently disable the checks it backs.
    REQUIRED_FILES: tuple[str, ...] = (
        "source-allowlist.yaml",
        "base-images.yaml",
        "tag-taxonomy.yaml",
    )

    @staticmethod
    def _load_mapping(path: Path, *, required: bool) -> tuple[dict, str | None]:
        """Load a policy YAML file that must be a top-level mapping.

        Returns ``(mapping, error)``. A parse failure, a read failure, or a
        non-mapping top-level document is always an error. For a *required*
        security-control policy, a missing or empty file is also an error, so
        deleting or failing to check out a policy can never fail open.
        """
        if not path.exists():
            if required:
                return {}, (
                    f"{path.name} is required but is missing. This policy is a "
                    f"security control; a missing file must not silently disable "
                    f"the checks it backs."
                )
            return {}, None
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
            return {}, f"{path.name} could not be parsed: {e}"
        if raw is None:
            if required:
                return {}, (
                    f"{path.name} is empty. A required policy must define its "
                    f"configuration explicitly."
                )
            return {}, None
        if not isinstance(raw, dict):
            return (
                {},
                f"{path.name}: top-level document must be a mapping, "
                f"got {type(raw).__name__}.",
            )
        return raw, None

    @classmethod
    def load(cls, repo: Path) -> "PolicyConfig":
        policy_dir = repo / ".github" / "policy"
        errors: list[tuple[str, str]] = []

        def _load(filename: str) -> tuple[str, dict]:
            rel = f".github/policy/{filename}"
            mapping, err = cls._load_mapping(
                policy_dir / filename, required=filename in cls.REQUIRED_FILES
            )
            if err:
                errors.append((rel, err))
            return rel, mapping

        def _str_list(rel: str, mapping: dict, key: str) -> list[str]:
            """A field that must be a list of strings, or absent."""
            val = mapping.get(key)
            if val is None:
                return []
            if not isinstance(val, list):
                errors.append((rel, f"{key!r} must be a list, got {type(val).__name__}."))
                return []
            out: list[str] = []
            for i, item in enumerate(val):
                if isinstance(item, str):
                    out.append(item)
                else:
                    errors.append((rel, f"{key}[{i}] must be a string, got {type(item).__name__}."))
            return out

        def _mapping_list_field(rel: str, mapping: dict, key: str, subkey: str) -> list[str]:
            """A field that must be a list of mappings each carrying ``subkey``."""
            val = mapping.get(key)
            if val is None:
                return []
            if not isinstance(val, list):
                errors.append((rel, f"{key!r} must be a list, got {type(val).__name__}."))
                return []
            out: list[str] = []
            for i, item in enumerate(val):
                if not isinstance(item, dict):
                    errors.append((rel, f"{key}[{i}] must be a mapping, got {type(item).__name__}."))
                    continue
                sub = item.get(subkey)
                if sub is None:
                    continue
                if isinstance(sub, str):
                    out.append(sub)
                else:
                    errors.append((rel, f"{key}[{i}].{subkey} must be a string, got {type(sub).__name__}."))
            return out

        def _bool_field(rel: str, mapping: dict, key: str, default: bool) -> bool:
            """A field that must be a real boolean; strings like 'false' are rejected."""
            if key not in mapping:
                return default
            val = mapping[key]
            if not isinstance(val, bool):
                errors.append((
                    rel,
                    f"{key!r} must be a boolean (true/false), got {type(val).__name__}. "
                    f"A quoted value such as \"false\" is not accepted.",
                ))
                return default
            return val

        al_rel, allowlist = _load("source-allowlist.yaml")
        bi_rel, base_images = _load("base-images.yaml")
        tx_rel, taxonomy = _load("tag-taxonomy.yaml")

        domains = taxonomy.get("domains")
        domain_tags: set[str] = set()
        if domains is not None:
            if not isinstance(domains, dict):
                errors.append((tx_rel, f"'domains' must be a mapping of group -> list of tags, got {type(domains).__name__}."))
            else:
                for group, tags in domains.items():
                    if not isinstance(tags, list):
                        errors.append((tx_rel, f"domains.{group} must be a list of tags, got {type(tags).__name__}."))
                        continue
                    for i, tag in enumerate(tags):
                        if isinstance(tag, str):
                            domain_tags.add(tag.lower())
                        else:
                            errors.append((tx_rel, f"domains.{group}[{i}] must be a string, got {type(tag).__name__}."))

        return cls(
            allowed_extensions=frozenset(
                e.lower() for e in _str_list(al_rel, allowlist, "extensions")
            ),
            allowed_filenames=frozenset(_str_list(al_rel, allowlist, "filenames")),
            allowed_patterns=tuple(_str_list(al_rel, allowlist, "patterns")),
            exempt_directories=frozenset(
                d.strip("/") for d in _str_list(al_rel, allowlist, "exempt_directories")
            ),
            model_weight_extensions=frozenset(
                e.lower() for e in _str_list(al_rel, allowlist, "model_weight_extensions")
            ),
            allow_docker_official_images=_bool_field(
                bi_rel, base_images, "allow_docker_official_images", True
            ),
            trusted_registries=frozenset(
                h.lower() for h in _mapping_list_field(bi_rel, base_images, "registries", "host")
            ),
            approved_namespaces=frozenset(
                n.lower() for n in _mapping_list_field(bi_rel, base_images, "namespaces", "ref")
            ),
            floating_tags=frozenset(
                t.lower() for t in _str_list(bi_rel, base_images, "floating_tags")
            ),
            domain_tags=frozenset(domain_tags),
            reserved_tag_prefixes=tuple(
                p.lower() for p in _str_list(tx_rel, taxonomy, "reserved_prefixes")
            ),
            computed_tags=frozenset(
                t.lower() for t in _str_list(tx_rel, taxonomy, "computed")
            ),
            config_errors=tuple(errors),
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
