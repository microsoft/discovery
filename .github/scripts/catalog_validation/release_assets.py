"""Validation for release manifests and Discovery Toolbox VSIX pointers."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .findings import Failure
from .schemas import load_json_schema, validate_against_schema


_DISCOVERY_MANIFEST_ROOT = "docs/discovery-app/releases/manifests/"
_DISCOVERY_MANIFEST_SCHEMA = "discovery-release-manifest-schema.json"
_TOOLBOX_ROOT = "utilities/discovery-toolbox/"
_TOOLBOX_VSIX_ROOT = f"{_TOOLBOX_ROOT}vsix/"
_TOOLBOX_POINTER = f"{_TOOLBOX_VSIX_ROOT}latest.json"
_TOOLBOX_SCHEMA = "discovery-toolbox-release-schema.json"
_TOOLBOX_VSIX_NAME = re.compile(
    r"^DiscoveryToolbox-v"
    r"(?P<version>[0-9]+\.[0-9]+\.[0-9]+"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)\.vsix$"
)
_SEMANTIC_VERSION = re.compile(
    r"^(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)"
    r"(?P<suffix>[-+].*)?$"
)


def _schema_path(repo: Path, name: str) -> Path:
    return repo / "docs" / "schemas" / name


def _load_document(path: Path, rule_id: str, relative: str) -> tuple[Any, list[Failure]]:
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream), []
    except (json.JSONDecodeError, OSError) as error:
        return None, [Failure(rule_id, relative, f"Could not load JSON: {error}")]


def _schema_failures(
    repo: Path,
    schema_name: str,
    rule_id: str,
    relative: str,
    document: Any,
) -> list[Failure]:
    schema_relative = f"docs/schemas/{schema_name}"
    schema = load_json_schema(_schema_path(repo, schema_name))
    if schema is None:
        return [Failure(
            "CFG-003",
            schema_relative,
            f"{schema_relative} is missing or is not a usable Draft 7 schema. "
            f"{rule_id} cannot run safely.",
        )]
    return [
        Failure(
            rule_id,
            relative,
            f"Schema validation failed: {message}",
        )
        for message in validate_against_schema(document, schema)
    ]


def _version_core(version: str) -> tuple[int, int, int] | None:
    match = _SEMANTIC_VERSION.fullmatch(version)
    if match is None:
        return None
    return tuple(
        int(match.group(part))
        for part in ("major", "minor", "patch")
    )


def _check_discovery_manifest(repo: Path, relative: str) -> list[Failure]:
    path = repo / Path(relative)
    if not path.is_file():
        return [Failure(
            "REL-001",
            relative,
            "Release manifests cannot be deleted through the automated fast lane.",
        )]

    document, failures = _load_document(path, "REL-001", relative)
    if failures:
        return failures
    failures.extend(_schema_failures(
        repo,
        _DISCOVERY_MANIFEST_SCHEMA,
        "REL-001",
        relative,
        document,
    ))
    if failures or not isinstance(document, dict):
        return failures

    expected_ring = path.stem
    if document.get("ring") != expected_ring:
        failures.append(Failure(
            "REL-001",
            relative,
            f"Manifest ring must equal its filename: expected '{expected_ring}'.",
        ))

    latest = _version_core(str(document.get("latestVersion", "")))
    minimum = _version_core(str(document.get("minimumVersion", "")))
    if latest is not None and minimum is not None and minimum > latest:
        failures.append(Failure(
            "REL-001",
            relative,
            "minimumVersion cannot be newer than latestVersion.",
        ))
    return failures


def _check_toolbox_release(repo: Path) -> list[Failure]:
    pointer_path = repo / Path(_TOOLBOX_POINTER)
    document, failures = _load_document(
        pointer_path,
        "REL-002",
        _TOOLBOX_POINTER,
    )
    if failures:
        return failures
    failures.extend(_schema_failures(
        repo,
        _TOOLBOX_SCHEMA,
        "REL-002",
        _TOOLBOX_POINTER,
        document,
    ))
    if failures or not isinstance(document, dict):
        return failures

    version = str(document.get("version", ""))
    expected_pointer = f"vsix/DiscoveryToolbox-v{version}.vsix"
    if document.get("vsixPath") != expected_pointer:
        failures.append(Failure(
            "REL-002",
            _TOOLBOX_POINTER,
            f"vsixPath must equal '{expected_pointer}' for version '{version}'.",
        ))

    vsix_dir = repo / Path(_TOOLBOX_VSIX_ROOT)
    published_vsix = sorted(vsix_dir.glob("DiscoveryToolbox-v*.vsix"))
    if len(published_vsix) != 1:
        failures.append(Failure(
            "REL-002",
            _TOOLBOX_VSIX_ROOT.rstrip("/"),
            "Exactly one published DiscoveryToolbox VSIX must remain after a release.",
        ))
        return failures

    vsix_path = published_vsix[0]
    name_match = _TOOLBOX_VSIX_NAME.fullmatch(vsix_path.name)
    if name_match is None or name_match.group("version") != version:
        failures.append(Failure(
            "REL-002",
            vsix_path.relative_to(repo).as_posix(),
            "Published VSIX filename version must match latest.json.",
        ))
        return failures

    digest = hashlib.sha256(vsix_path.read_bytes()).hexdigest()
    if document.get("sha256") != digest:
        failures.append(Failure(
            "REL-002",
            _TOOLBOX_POINTER,
            f"sha256 does not match {vsix_path.name}; expected {digest}.",
        ))
    return failures


def check_release_assets(repo: Path, changed_files: list[str]) -> list[Failure]:
    """Validate release assets whenever a governed release surface changes."""
    normalized = [path.replace("\\", "/") for path in changed_files]
    failures: list[Failure] = []

    manifest_changes = [
        path for path in normalized if path.startswith(_DISCOVERY_MANIFEST_ROOT)
    ]
    for relative in manifest_changes:
        if not relative.endswith(".json"):
            failures.append(Failure(
                "REL-001",
                relative,
                "Discovery release manifests must be JSON files.",
            ))
            continue
        failures.extend(_check_discovery_manifest(repo, relative))

    toolbox_changes = [
        path for path in normalized if path.startswith(_TOOLBOX_ROOT)
    ]
    if toolbox_changes:
        allowed = all(
            path in {
                f"{_TOOLBOX_ROOT}README.md",
                f"{_TOOLBOX_ROOT}PRIVACY.md",
            }
            or
            path == _TOOLBOX_POINTER
            or (
                path.startswith(_TOOLBOX_VSIX_ROOT)
                and _TOOLBOX_VSIX_NAME.fullmatch(Path(path).name) is not None
            )
            for path in toolbox_changes
        )
        if not allowed:
            failures.append(Failure(
                "REL-002",
                _TOOLBOX_ROOT.rstrip("/"),
                "Discovery Toolbox changes are limited to README.md, PRIVACY.md, "
                "latest.json, and versioned VSIX packages. Add executable source "
                "under a separately CODEOWNED utility path.",
            ))
        if not any(path.startswith(_TOOLBOX_VSIX_ROOT) for path in toolbox_changes):
            return failures
        failures.extend(_check_toolbox_release(repo))

    return failures
