"""Shared document loading and JSON Schema validation helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from referencing import Registry, Resource


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def load_yaml(path: Path) -> tuple[Any, str | None]:
    """Load YAML and return the document plus an optional parse error."""
    try:
        with path.open(encoding="utf-8") as stream:
            return yaml.safe_load(stream), None
    except yaml.YAMLError as error:
        return None, str(error)
    except OSError as error:
        return None, str(error)


def load_json_schema(path: Path) -> dict[str, Any] | None:
    try:
        data = load_json(path)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def load_schema(repo_root: Path, schema_name: str) -> dict[str, Any]:
    schema_path = repo_root / "docs" / "schemas" / schema_name
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")
    schema = load_json(schema_path)
    if not isinstance(schema, dict):
        raise TypeError(f"Schema must be a JSON object: {schema_path}")
    return schema


def build_schema_registry(common_schema: dict[str, Any]) -> Registry:
    return Registry().with_resource(
        "common-schema.json",
        Resource.from_contents(common_schema),
    )


@dataclass(frozen=True)
class CatalogSchemas:
    agent: dict[str, Any] | None
    tool: dict[str, Any] | None
    metadata: dict[str, Any] | None
    common: dict[str, Any] | None
    registry: Registry | None

    @classmethod
    def load(cls, repo: Path) -> "CatalogSchemas":
        schema_dir = repo / "docs" / "schemas"
        common = load_json_schema(schema_dir / "common-schema.json")
        return cls(
            agent=load_json_schema(schema_dir / "agent-schema-v2.json"),
            tool=load_json_schema(schema_dir / "tool-definition-schema.json"),
            metadata=load_json_schema(schema_dir / "metadata-schema.json"),
            common=common,
            registry=build_schema_registry(common) if common is not None else None,
        )

    def warnings(self) -> list[str]:
        messages: list[str] = []
        if self.agent is None:
            messages.append(
                "docs/schemas/agent-schema-v2.json could not be loaded. "
                "SCH-010-013 skipped."
            )
        if self.tool is None:
            messages.append(
                "docs/schemas/tool-definition-schema.json could not be loaded. "
                "SCH-014-015 skipped."
            )
        if self.metadata is None:
            messages.append(
                "docs/schemas/metadata-schema.json could not be loaded. Full "
                "metadata schema validation skipped."
            )
        if self.common is None:
            messages.append(
                "docs/schemas/common-schema.json could not be loaded. External "
                "schema references may not resolve."
            )
        return messages


def iter_schema_errors(
    data: Any,
    schema: dict[str, Any],
    schema_registry: Registry | None = None,
) -> list[jsonschema.ValidationError]:
    validator_kwargs: dict[str, object] = {
        "format_checker": jsonschema.FormatChecker(),
    }
    if schema_registry is not None:
        validator_kwargs["registry"] = schema_registry
    validator = jsonschema.Draft7Validator(schema, **validator_kwargs)
    return sorted(validator.iter_errors(data), key=lambda error: list(error.path))


def validate_against_schema(
    data: Any,
    schema: dict[str, Any],
    schema_registry: Registry | None = None,
) -> list[str]:
    """Return stable dot-path messages for all schema violations."""
    try:
        return [
            f"{'.'.join(str(part) for part in error.path) or '(root)'}: {error.message}"
            for error in iter_schema_errors(data, schema, schema_registry)
        ]
    except Exception as error:
        return [str(error)]


class _DuplicateKeySafeLoader(yaml.SafeLoader):
    """SafeLoader that raises ConstructorError on duplicate mapping keys."""


def _no_duplicates_constructor(
    loader: yaml.Loader,
    node: yaml.Node,
    deep: bool = False,
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_DuplicateKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _no_duplicates_constructor,
)


def find_duplicate_yaml_key(path: Path) -> str | None:
    """Describe the first duplicate YAML mapping key, if present."""
    try:
        with path.open(encoding="utf-8") as stream:
            yaml.load(stream, Loader=_DuplicateKeySafeLoader)
        return None
    except yaml.constructor.ConstructorError as error:
        mark = getattr(error, "problem_mark", None) or error.context_mark
        line = (mark.line + 1) if mark else 1
        return f"line {line}: {error.problem}"
    except (yaml.YAMLError, OSError):
        return None