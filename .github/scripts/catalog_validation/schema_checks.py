"""Schema-backed and cross-field validation for agent catalog documents."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from jsonschema.exceptions import ValidationError
from referencing import Registry

from .findings import Failure
from .schemas import iter_schema_errors, load_json, load_yaml


def _schema_findings(
    rule_id: str,
    rel: str,
    prefix: str,
    data: Any,
    schema: dict[str, Any],
    schema_registry: Registry | None,
    rule_for_error: Callable[[ValidationError], str] | None = None,
) -> list[Failure]:
    try:
        errors = iter_schema_errors(data, schema, schema_registry)
    except Exception as error:
        return [Failure(rule_id, rel, f"{prefix}: {error}")]
    return [
        Failure(
            rule_for_error(error) if rule_for_error else rule_id,
            rel,
            f"{prefix}: "
            f"{'.'.join(str(part) for part in error.path) or '(root)'}: {error.message}",
        )
        for error in errors
    ]


def _metadata_rule_for_error(error: ValidationError) -> str:
    path = tuple(error.absolute_path)
    if path[:1] == ("type",):
        return "SCH-002"
    if path[:1] == ("tags",):
        return "SCH-004" if len(path) == 1 else "SCH-005"
    if path[:1] == ("supported_regions",):
        return "SCH-006"
    if path[:2] == ("publisher", "contact"):
        return "SCH-008"
    if path[:2] == ("publisher", "support_url"):
        return "SCH-009"
    if path[:2] == ("publisher", "party"):
        return "SCH-031"
    if path[:1] == ("version",):
        return "SCH-017"
    return "SCH-001"


def _agent_rule_for_error(error: ValidationError) -> str:
    path = tuple(error.absolute_path)
    if path[:1] == ("kind",) or (error.validator == "required" and "'kind'" in error.message):
        return "SCH-011"
    if path[:1] == ("instructions",) or (
        error.validator == "required" and "'instructions'" in error.message
    ):
        return "SCH-036" if error.validator == "maxLength" else "SCH-012"
    if path[:1] == ("name",) or (error.validator == "required" and "'name'" in error.message):
        return "SCH-013"
    if path[:1] == ("version",):
        return "SCH-017"
    return "SCH-010"


def _tool_rule_for_error(error: ValidationError) -> str:
    path = tuple(error.absolute_path)
    if path[:1] == ("version",):
        return "SCH-017"
    if len(path) >= 4 and path[0] == "infra" and path[2:4] == ("image", "acr"):
        return "SCH-037"
    return "SCH-014"


def _load_valid_regions(repo: Path) -> set[str]:
    """Load region aliases for the legacy validate_pr compatibility API."""
    try:
        data = load_json(repo / "docs" / "schemas" / "azure-regions.json")
    except (OSError, ValueError):
        return set()
    return set(data) if isinstance(data, list) else set()


def _check_metadata(
    repo: Path,
    folder: Path,
    metadata_schema: dict[str, Any] | None,
    schema_registry: Registry | None,
) -> list[Failure]:
    metadata_path = repo / folder / "metadata.yaml"
    if not metadata_path.exists():
        return []

    metadata_rel = str(metadata_path.relative_to(repo))
    data, error = load_yaml(metadata_path)
    if error or data is None:
        return [Failure(
            "SCH-001",
            metadata_rel,
            f"metadata.yaml could not be parsed: {error}",
        )]

    failures: list[Failure] = []
    if metadata_schema:
        failures.extend(_schema_findings(
            "SCH-001",
            metadata_rel,
            "metadata.yaml does not conform to docs/schemas/metadata-schema.json",
            data,
            metadata_schema,
            schema_registry,
            _metadata_rule_for_error,
        ))
    if not isinstance(data, dict):
        return failures

    if not metadata_schema:
        for field in ("name", "type", "version", "publisher", "description", "tags"):
            if field not in data:
                failures.append(Failure(
                    "SCH-001",
                    metadata_rel,
                    f"metadata.yaml is missing required field '{field}'.",
                ))

    if folder.parts[0] != "agents":
        return failures

    associated_tools = data.get("associated_tools", [])
    if isinstance(associated_tools, list):
        for tool_path_value in associated_tools:
            if not isinstance(tool_path_value, str):
                continue
            if not (repo / tool_path_value.rstrip("/")).is_dir():
                failures.append(Failure(
                    "SCH-028",
                    metadata_rel,
                    f"metadata.yaml: associated_tools entry '{tool_path_value}' does "
                    "not exist as a directory in this repository.",
                ))

    tools_dir = repo / folder / "tools"
    if tools_dir.is_dir():
        actual_tool_dirs = {
            str(folder / "tools" / path.name).replace("\\", "/")
            for path in tools_dir.iterdir()
            if path.is_dir()
        }
        declared = {
            path.rstrip("/")
            for path in associated_tools
            if isinstance(path, str)
        } if isinstance(associated_tools, list) else set()
        for missing in sorted(actual_tool_dirs - declared):
            failures.append(Failure(
                "SCH-029",
                metadata_rel,
                f"metadata.yaml: tools directory '{missing}' exists but is not "
                "listed in associated_tools. Add it to associated_tools or remove "
                "the tools directory.",
            ))
    elif isinstance(associated_tools, list) and associated_tools:
        failures.append(Failure(
            "SCH-029",
            metadata_rel,
            "metadata.yaml: associated_tools lists tool paths but no tools/ "
            "directory exists under this agent folder.",
        ))

    return failures


def _check_agent(
    repo: Path,
    folder: Path,
    agent_schema: dict[str, Any] | None,
    schema_registry: Registry | None,
) -> list[Failure]:
    agent_path = repo / folder / "agent.yaml"
    if not agent_path.exists() or not agent_schema:
        return []

    agent_rel = str(agent_path.relative_to(repo))
    data, error = load_yaml(agent_path)
    if error or data is None:
        return [Failure(
            "SCH-010",
            agent_rel,
            f"agent.yaml could not be parsed: {error}",
        )]

    failures = _schema_findings(
        "SCH-010",
        agent_rel,
        "agent.yaml failed schema validation against docs/schemas/agent-schema-v2.json",
        data,
        agent_schema,
        schema_registry,
        _agent_rule_for_error,
    )
    if not isinstance(data, dict):
        return failures

    if (repo / folder / "tools").is_dir() and not data.get("discoveryExtensions"):
        failures.append(Failure(
            "SCH-030",
            agent_rel,
            "agent.yaml: 'discoveryExtensions' is required when the agent has a "
            "tools/ directory. The discoveryExtensions node must declare the "
            "Discovery-managed tools so they are wired up at deploy time. See "
            "docs/authoring-guide.md for the expected structure.",
        ))
    return failures


def _duplicate_values(items: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in items:
        if item in seen and item not in duplicates:
            duplicates.append(item)
        seen.add(item)
    return duplicates


def _check_tool(
    repo: Path,
    tool_path: Path,
    tool_schema: dict[str, Any],
    schema_registry: Registry | None,
) -> list[Failure]:
    tool_rel = str(tool_path.relative_to(repo))
    data, error = load_yaml(tool_path)
    if error or data is None:
        return [Failure(
            "SCH-014",
            tool_rel,
            f"tool.yaml could not be parsed: {error}",
        )]

    failures = _schema_findings(
        "SCH-014",
        tool_rel,
        "tool.yaml failed schema validation against docs/schemas/tool-definition-schema.json",
        data,
        tool_schema,
        schema_registry,
        _tool_rule_for_error,
    )
    if not isinstance(data, dict):
        return failures

    infra = [entry for entry in (data.get("infra") or []) if isinstance(entry, dict)]
    actions = [entry for entry in (data.get("actions") or []) if isinstance(entry, dict)]
    environments = [
        entry for entry in (data.get("code_environments") or [])
        if isinstance(entry, dict)
    ]
    infra_names = {entry.get("name") for entry in infra}
    for entry in [*actions, *environments]:
        node = entry.get("infra_node")
        if node and node not in infra_names:
            failures.append(Failure(
                "SCH-015",
                tool_rel,
                f"tool.yaml: infra_node '{node}' does not match any entry in infra[].name.",
            ))

    output_names: list[str] = []
    mount_paths: list[str] = []
    for action in actions:
        output_names.extend(
            configuration["output_name"]
            for configuration in (action.get("output_mount_configurations") or [])
            if isinstance(configuration, dict) and configuration.get("output_name")
        )
        mount_paths.extend(
            inline_file["mount_path"]
            for inline_file in (action.get("inline_files") or [])
            if isinstance(inline_file, dict) and inline_file.get("mount_path")
        )

    unique_groups = (
        ("infra[].name", [entry["name"] for entry in infra if entry.get("name")]),
        ("actions[].name", [entry["name"] for entry in actions if entry.get("name")]),
        ("actions[].output_mount_configurations[].output_name", output_names),
        ("actions[].inline_files[].mount_path", mount_paths),
    )
    for kind, values in unique_groups:
        duplicates = _duplicate_values(values)
        if duplicates:
            failures.append(Failure(
                "SCH-034",
                tool_rel,
                f"tool.yaml: duplicate value(s) in {kind}: {duplicates}. Each entry "
                "must be unique.",
            ))

    for action in actions:
        input_schema = action.get("input_schema") or {}
        if not isinstance(input_schema, dict):
            continue
        properties = input_schema.get("properties") or {}
        required = input_schema.get("required") or []
        missing = [name for name in required if name not in properties]
        if missing:
            failures.append(Failure(
                "SCH-035",
                tool_rel,
                f"tool.yaml: action '{action.get('name', '?')}' lists required input(s) "
                f"{missing} that are not defined under input_schema.properties.",
            ))
    return failures


def _check_tools(
    repo: Path,
    folder: Path,
    tool_schema: dict[str, Any] | None,
    schema_registry: Registry | None,
) -> list[Failure]:
    tools_dir = repo / folder / "tools"
    if not tools_dir.is_dir() or not tool_schema:
        return []

    failures: list[Failure] = []
    for tool_dir in [path for path in tools_dir.iterdir() if path.is_dir()]:
        tool_path = tool_dir / "tool.yaml"
        if tool_path.exists():
            failures.extend(_check_tool(repo, tool_path, tool_schema, schema_registry))
    return failures


def check_schema(
    repo: Path,
    folders: set[Path],
    agent_schema: dict[str, Any] | None,
    tool_schema: dict[str, Any] | None,
    metadata_schema: dict[str, Any] | None = None,
    schema_registry: Registry | None = None,
) -> list[Failure]:
    """Run schema and cross-field checks for every changed agent folder."""
    failures: list[Failure] = []
    for folder in folders:
        failures.extend(_check_metadata(
            repo,
            folder,
            metadata_schema,
            schema_registry,
        ))
        failures.extend(_check_agent(repo, folder, agent_schema, schema_registry))
        failures.extend(_check_tools(repo, folder, tool_schema, schema_registry))
    return failures