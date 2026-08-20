"""Security invariants for catalog JSON Schemas."""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml
from jsonschema import Draft7Validator, FormatChecker
from referencing import Registry, Resource

from catalog_validation.schema_checks import check_schema
from catalog_validation.schemas import CatalogSchemas


REPO_ROOT = Path(
    os.environ.get("DISCOVERY_CATALOG_ROOT", Path(__file__).resolve().parents[2])
).resolve()
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"
SCHEMA_PATHS = sorted(SCHEMA_DIR.glob("*schema*.json"))

DOCUMENT_GROUPS = (
    ("metadata-schema.json", sorted(REPO_ROOT.glob("agents/*/metadata.yaml"))),
    ("agent-schema-v2.json", sorted(REPO_ROOT.glob("agents/*/agent.yaml"))),
    ("tool-definition-schema.json", sorted(REPO_ROOT.glob("agents/*/tools/*/tool.yaml"))),
    ("starter-kit-schema.json", sorted(REPO_ROOT.glob("starter-kits/*/kit.json"))),
    ("registry-schema.json", [REPO_ROOT / ".auto-registry" / "agent-registry.json"]),
    (
        "starter-kit-registry-schema.json",
        [REPO_ROOT / ".auto-registry" / "starter-kit-registry.json"],
    ),
)

SCHEMA_MAP_KEYWORDS = ("$defs", "definitions", "properties", "patternProperties")
SCHEMA_VALUE_KEYWORDS = (
    "additionalProperties",
    "contains",
    "else",
    "if",
    "items",
    "not",
    "propertyNames",
    "then",
)
SCHEMA_ARRAY_KEYWORDS = ("allOf", "anyOf", "oneOf")
VALIDATION_KEYWORDS = {
    "$ref",
    "allOf",
    "anyOf",
    "const",
    "enum",
    "if",
    "not",
    "oneOf",
    "properties",
    "required",
    "type",
}


def iter_subschemas(schema: dict[str, Any], pointer: str = "#") -> Iterator[tuple[str, dict[str, Any]]]:
    yield pointer, schema

    for keyword in SCHEMA_MAP_KEYWORDS:
        children = schema.get(keyword, {})
        if isinstance(children, dict):
            for name, child in children.items():
                if isinstance(child, dict):
                    yield from iter_subschemas(child, f"{pointer}/{keyword}/{name}")

    for keyword in SCHEMA_VALUE_KEYWORDS:
        child = schema.get(keyword)
        if isinstance(child, dict):
            yield from iter_subschemas(child, f"{pointer}/{keyword}")

    for keyword in SCHEMA_ARRAY_KEYWORDS:
        children = schema.get(keyword, [])
        if isinstance(children, list):
            for index, child in enumerate(children):
                if isinstance(child, dict):
                    yield from iter_subschemas(child, f"{pointer}/{keyword}/{index}")


def node_violations(pointer: str, schema: dict[str, Any]) -> list[str]:
    violations: list[str] = []

    if not VALIDATION_KEYWORDS.intersection(schema):
        violations.append(f"{pointer}: has no type, reference, composition, enum, or const")

    node_type = schema.get("type")
    finite_value_set = "const" in schema or "enum" in schema

    if node_type == "string" and not finite_value_set and "maxLength" not in schema:
        violations.append(f"{pointer}: string has no maxLength")
    elif node_type == "array":
        if "maxItems" not in schema:
            violations.append(f"{pointer}: array has no maxItems")
        if "items" not in schema:
            violations.append(f"{pointer}: array has no items schema")
    elif node_type == "object":
        additional = schema.get("additionalProperties")
        if additional is True or additional is None:
            violations.append(f"{pointer}: object permits untyped additional properties")
        elif isinstance(additional, dict) and "maxProperties" not in schema:
            violations.append(f"{pointer}: extensible object has no maxProperties")
    elif node_type in {"integer", "number"} and not finite_value_set:
        if "minimum" not in schema or "maximum" not in schema:
            violations.append(f"{pointer}: numeric value must declare minimum and maximum")

    return violations


def build_validator(schema_name: str) -> Draft7Validator:
    schemas = {
        path.name: json.loads(path.read_text(encoding="utf-8")) for path in SCHEMA_PATHS
    }
    registry = Registry().with_resources(
        (name, Resource.from_contents(schema)) for name, schema in schemas.items()
    )
    return Draft7Validator(
        schemas[schema_name], registry=registry, format_checker=FormatChecker()
    )


def load_document(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text) if path.suffix == ".yaml" else json.loads(text)


@pytest.mark.parametrize("schema_path", SCHEMA_PATHS, ids=lambda path: path.name)
def test_schema_nodes_are_typed_and_bounded(schema_path: Path):
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    violations = [
        violation
        for pointer, subschema in iter_subschemas(schema)
        for violation in node_violations(pointer, subschema)
    ]
    assert not violations, "\n" + "\n".join(violations)


def test_azure_region_allowlist_is_bounded():
    regions = json.loads((SCHEMA_DIR / "azure-regions.json").read_text(encoding="utf-8"))

    assert isinstance(regions, list)
    assert 1 <= len(regions) <= 100
    assert len(regions) == len(set(regions))
    assert all(
        isinstance(region, str)
        and len(region) <= 32
        and re.fullmatch(r"[a-z][a-z0-9]*", region)
        for region in regions
    )


@pytest.mark.parametrize("schema_path", SCHEMA_PATHS, ids=lambda path: path.name)
def test_schema_is_valid_draft7(schema_path: Path):
    Draft7Validator.check_schema(json.loads(schema_path.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("schema_name", "document_paths"),
    DOCUMENT_GROUPS,
    ids=[schema_name for schema_name, _ in DOCUMENT_GROUPS],
)
def test_catalog_documents_conform(schema_name: str, document_paths: list[Path]):
    validator = build_validator(schema_name)

    errors: list[str] = []
    for document_path in document_paths:
        assert document_path.is_file(), f"Missing generated document: {document_path}"
        document = load_document(document_path)
        for error in validator.iter_errors(document):
            instance_path = "/".join(str(part) for part in error.absolute_path) or "(root)"
            errors.append(
                f"{document_path.relative_to(REPO_ROOT)} at {instance_path}: {error.message}"
            )

    assert not errors, "\n" + "\n".join(errors)


def test_metadata_rejects_oversized_and_malformed_publisher_input():
    validator = build_validator("metadata-schema.json")
    valid = load_document(next(REPO_ROOT.glob("agents/*/metadata.yaml")))

    oversized = deepcopy(valid)
    oversized["publisher"]["name"] = "x" * 201
    assert not validator.is_valid(oversized)

    insecure_url = deepcopy(valid)
    insecure_url["publisher"]["support_url"] = "http://example.com/support"
    assert not validator.is_valid(insecure_url)


def test_agent_rejects_oversized_prompt_and_deep_extension_input():
    validator = build_validator("agent-schema-v2.json")
    valid = load_document(next(REPO_ROOT.glob("agents/*/agent.yaml")))

    for instructions in ("", " \t\n"):
        blank = deepcopy(valid)
        blank["instructions"] = instructions
        assert not validator.is_valid(blank)

    oversized = deepcopy(valid)
    oversized["instructions"] = "x" * 32001
    assert not validator.is_valid(oversized)

    deeply_nested = deepcopy(valid)
    deeply_nested["metadata"] = {"level1": {"level2": {"level3": {"level4": "x"}}}}
    assert not validator.is_valid(deeply_nested)


def test_blank_agent_instructions_emit_sch_012(tmp_path: Path):
    agent = load_document(next(REPO_ROOT.glob("agents/*/agent.yaml")))
    agent["instructions"] = " \t\n"
    agent_path = tmp_path / "agents" / "sample" / "agent.yaml"
    agent_path.parent.mkdir(parents=True)
    agent_path.write_text(yaml.safe_dump(agent), encoding="utf-8")

    schemas = CatalogSchemas.load(REPO_ROOT)
    failures = check_schema(
        tmp_path,
        {Path("agents/sample")},
        schemas.agent,
        schemas.tool,
        schemas.metadata,
        schemas.registry,
    )

    assert {failure.rule_id for failure in failures} == {"SCH-012"}


def test_tool_rejects_excessive_resources_and_unknown_parameter_keywords():
    validator = build_validator("tool-definition-schema.json")
    path = REPO_ROOT / "agents" / "molecular-groups" / "tools" / "molecular-groups" / "tool.yaml"
    valid = load_document(path)

    excessive_compute = deepcopy(valid)
    excessive_compute["infra"][0]["compute"]["max_resources"]["cpu"] = 4097
    assert not validator.is_valid(excessive_compute)

    for field, value in (
        ("cpu", "9999"),
        ("ram", "999999Ti"),
        ("storage", "9999999Ti"),
        ("gpu", "9999"),
    ):
        string_bypass = deepcopy(valid)
        string_bypass["infra"][0]["compute"]["max_resources"][field] = value
        assert not validator.is_valid(string_bypass), f"accepted oversized {field}: {value}"

    unknown_keyword = deepcopy(valid)
    unknown_keyword["actions"][0]["input_schema"]["properties"]["input_directory"][
        "shell"
    ] = True
    assert not validator.is_valid(unknown_keyword)

    for invalid_acr in (
        "{name}/tool:1.0.0",
        "hardcoded.azurecr.io/tool:1.0.0",
    ):
        invalid_image = deepcopy(valid)
        invalid_image["infra"][0]["image"]["acr"] = invalid_acr
        assert not validator.is_valid(invalid_image), f"accepted invalid ACR: {invalid_acr}"


def test_starter_kit_rejects_oversized_collections_and_insecure_urls():
    validator = build_validator("starter-kit-schema.json")
    valid = load_document(next(REPO_ROOT.glob("starter-kits/*/kit.json")))

    too_many_keywords = deepcopy(valid)
    too_many_keywords["keywords"] = [f"keyword-{index}" for index in range(33)]
    assert not validator.is_valid(too_many_keywords)

    insecure_url = deepcopy(valid)
    insecure_url["homepage"] = "http://example.com"
    assert not validator.is_valid(insecure_url)


def test_starter_kit_registry_rejects_unvalidated_pass_through_fields():
    validator = build_validator("starter-kit-registry-schema.json")
    valid = load_document(REPO_ROOT / ".auto-registry" / "starter-kit-registry.json")
    injected = deepcopy(valid)
    injected["kits"][0]["privateConfig"] = {"token": "not-allowed"}

    assert not validator.is_valid(injected)