"""Structural validation for changed agent folders."""

from __future__ import annotations

from pathlib import Path

from .findings import Failure
from .schemas import find_duplicate_yaml_key, load_yaml


def check_structural(
    repo: Path,
    folders: set[Path],
    changed_files: list[str],
) -> list[Failure]:
    del changed_files  # Reserved for structural checks that need diff context.
    failures: list[Failure] = []

    for folder in folders:
        abs_folder = repo / folder
        rel = str(folder)

        if not (abs_folder / "metadata.yaml").exists():
            failures.append(Failure(
                "STR-001",
                f"{rel}/metadata.yaml",
                "metadata.yaml is missing. Every agent must include a metadata.yaml. "
                "See docs/schemas/metadata-schema.json",
            ))

        if not (abs_folder / "README.md").exists():
            failures.append(Failure(
                "STR-002",
                f"{rel}/README.md",
                "README.md is missing. Provide a usage guide for your agent.",
            ))

        is_agent = folder.parts[0] == "agents"
        if is_agent and not (abs_folder / "agent.yaml").exists():
            failures.append(Failure(
                "STR-003",
                f"{rel}/agent.yaml",
                "agent.yaml is required for every agent.",
            ))

        tools_dir = abs_folder / "tools"
        if is_agent and tools_dir.is_dir():
            for tool_folder in [path for path in tools_dir.iterdir() if path.is_dir()]:
                if not (tool_folder / "tool.yaml").exists():
                    failures.append(Failure(
                        "STR-005",
                        str((tool_folder / "tool.yaml").relative_to(repo)),
                        f"tool.yaml is missing in tools/{tool_folder.name}/. "
                        "Every tool must have a tool.yaml definition.",
                    ))
                if not (tool_folder / "Dockerfile").exists():
                    failures.append(Failure(
                        "STR-006",
                        str((tool_folder / "Dockerfile").relative_to(repo)),
                        f"Dockerfile is missing in tools/{tool_folder.name}/. "
                        "Tools require a Dockerfile.",
                    ))

        if is_agent:
            for subdir in abs_folder.iterdir():
                if not subdir.is_dir() or subdir.name == "tools":
                    continue
                has_tool_contents = (
                    (subdir / "tool.yaml").exists()
                    or any(
                        (path / "tool.yaml").exists()
                        for path in subdir.iterdir()
                        if path.is_dir()
                    )
                )
                if has_tool_contents:
                    failures.append(Failure(
                        "STR-009",
                        str(subdir.relative_to(repo)),
                        f"Directory '{subdir.name}' appears to be a misnamed tools directory. "
                        "The tools subdirectory must be named exactly 'tools'. "
                        f"Rename '{subdir.name}/' to 'tools/'.",
                    ))

            metadata_path = abs_folder / "metadata.yaml"
            if metadata_path.exists():
                data, error = load_yaml(metadata_path)
                if not error and isinstance(data, dict):
                    metadata_name = data.get("name")
                    if metadata_name and metadata_name != folder.name:
                        failures.append(Failure(
                            "STR-010",
                            str(metadata_path.relative_to(repo)),
                            f"metadata.yaml: 'name' is '{metadata_name}' but the agent "
                            f"folder is '{folder.name}'. The two must be identical; rename "
                            "the folder or update 'name' so they match.",
                        ))

            yaml_candidates = [abs_folder / "metadata.yaml", abs_folder / "agent.yaml"]
            if tools_dir.is_dir():
                yaml_candidates.extend(
                    tool_dir / "tool.yaml"
                    for tool_dir in tools_dir.iterdir()
                    if tool_dir.is_dir() and (tool_dir / "tool.yaml").exists()
                )
            for yaml_path in yaml_candidates:
                if not yaml_path.exists():
                    continue
                duplicate = find_duplicate_yaml_key(yaml_path)
                if duplicate:
                    failures.append(Failure(
                        "STR-011",
                        str(yaml_path.relative_to(repo)),
                        f"YAML duplicate mapping key detected ({duplicate}). PyYAML "
                        "silently keeps the last value when keys repeat; remove the "
                        "duplicate to make the file unambiguous.",
                    ))

    return failures