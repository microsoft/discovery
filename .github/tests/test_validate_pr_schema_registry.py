"""Regression tests for external ``$ref`` resolution in validate_pr.

The catalog schemas reference shared definitions via
``common-schema.json#/definitions/...``. Modern jsonschema raises
``Unresolvable`` for such references unless a ``referencing`` registry is
supplied. These tests pin the resolver so schemas can be modularised without
the base validator regressing to "Unresolvable" errors.
"""

from __future__ import annotations

from pathlib import Path

from validate_pr import build_schema_registry, validate_against_schema

REPO_ROOT = Path(__file__).resolve().parents[2]

_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "version": {"$ref": "common-schema.json#/definitions/semanticVersion"},
    },
    "required": ["version"],
    "additionalProperties": False,
}


def test_build_schema_registry_returns_registry_when_common_present():
    assert build_schema_registry(REPO_ROOT) is not None


def test_registry_resolves_external_ref_for_valid_data():
    registry = build_schema_registry(REPO_ROOT)
    assert registry is not None
    errors = validate_against_schema({"version": "1.2.3"}, _REF_SCHEMA, registry)
    assert errors == [], errors


def test_registry_resolves_external_ref_and_rejects_invalid_data():
    registry = build_schema_registry(REPO_ROOT)
    errors = validate_against_schema({"version": "not-a-version"}, _REF_SCHEMA, registry)
    assert errors, "expected the referenced semanticVersion pattern to reject bad input"
    assert not any("Unresolvable" in e for e in errors), errors


def test_missing_registry_cannot_resolve_external_ref():
    # Documents why the registry is required: without it the external $ref is
    # unresolvable. This is exactly the failure the resolver fixes.
    errors = validate_against_schema({"version": "1.2.3"}, _REF_SCHEMA)
    assert any("Unresolvable" in e for e in errors), errors


def test_self_contained_schema_unaffected_without_registry():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    assert validate_against_schema({"name": "ok"}, schema) == []
    assert validate_against_schema({}, schema)
