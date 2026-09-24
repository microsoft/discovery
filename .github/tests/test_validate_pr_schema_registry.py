"""Regression tests for external ``$ref`` resolution in validation schemas."""

from __future__ import annotations

from pathlib import Path

from catalog_validation.schemas import (
    build_schema_registry,
    load_schema,
    validate_against_schema,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "version": {"$ref": "common-schema.json#/definitions/semanticVersion"},
    },
    "required": ["version"],
    "additionalProperties": False,
}


def _registry():
    return build_schema_registry(load_schema(REPO_ROOT, "common-schema.json"))


def test_build_schema_registry_returns_registry_when_common_present():
    assert _registry() is not None


def test_registry_resolves_external_ref_for_valid_data():
    errors = validate_against_schema(
        {"version": "1.2.3"},
        _REF_SCHEMA,
        _registry(),
    )
    assert errors == [], errors


def test_registry_resolves_external_ref_and_rejects_invalid_data():
    errors = validate_against_schema(
        {"version": "not-a-version"},
        _REF_SCHEMA,
        _registry(),
    )
    assert errors, "expected the referenced semanticVersion pattern to reject bad input"
    assert not any("Unresolvable" in error for error in errors), errors


def test_missing_registry_cannot_resolve_external_ref():
    errors = validate_against_schema({"version": "1.2.3"}, _REF_SCHEMA)
    assert any("Unresolvable" in error for error in errors), errors


def test_self_contained_schema_unaffected_without_registry():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    assert validate_against_schema({"name": "ok"}, schema) == []
    assert validate_against_schema({}, schema)
