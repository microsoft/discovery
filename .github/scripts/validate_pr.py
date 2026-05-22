#!/usr/bin/env python3
"""
validate_pr.py — PR validation script for the Discovery catalog.

Runs all structural / schema / policy / documentation checks against the files
changed in a pull request. Collects ALL failures before reporting so the PR
submitter receives a complete picture in one pass.

Usage:
    python validate_pr.py --changed-files <file> --repo-root <path> --output <json>

Arguments:
    --changed-files   Path to a newline-delimited file listing changed file paths
                      (relative to repo root).
    --repo-root       Absolute path to the repository root. Defaults to cwd.
    --output          Path to write the JSON results file consumed by the
                      GitHub Actions posting step.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from model_weights_sniffer import MODEL_WEIGHT_EXTENSIONS, sniff

# ── Constants ────────────────────────────────────────────

# Binaries blocked outright by POL-008. Model-weight formats are validated
# instead by POL-009 (see model_weights_sniffer.py).
_ALL_BLOCKED_BINARIES = {
    ".exe", ".dll", ".bin", ".zip", ".tar", ".gz", ".tgz", ".7z",
    ".rar", ".iso", ".img", ".dmg", ".pkg", ".deb", ".rpm",
    ".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".pb",
    ".h5", ".hdf5", ".pkl", ".joblib", ".npy", ".npz",
    ".gguf", ".tflite", ".engine", ".weights",
}
BLOCKED_BINARY_EXTENSIONS = _ALL_BLOCKED_BINARIES - set(MODEL_WEIGHT_EXTENSIONS)

# Model-weight payload size cap (POL-009). Files larger than this should
# live in container images or external storage, not in the catalog repo.
MODEL_WEIGHT_MAX_BYTES = 5 * 1024 ** 3  # 5 GB

# Pickle GLOBAL imports considered safe inside a torch state-dict checkpoint.
# Anything else triggers a POL-009 failure when picklescan flags it.
PICKLE_ALLOWLIST = frozenset({
    "torch", "torch._utils", "torch.nn", "torch.nn.modules",
    "torch.nn.parameter", "torch.storage", "torch._tensor",
    "collections", "collections.abc",
    "numpy", "numpy.core.multiarray", "numpy.core.numeric",
})

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HTTPS_URL_RE = re.compile(r"^https://")
TAG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
AGENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_yaml(path: Path) -> tuple[Any, str | None]:
    """Load a YAML file. Returns (data, error_message)."""
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f), None
    except yaml.YAMLError as e:
        return None, str(e)
    except OSError as e:
        return None, str(e)


def load_json_schema(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ── STR-011: YAML duplicate-key detection ────────────────────────────────────

class _DuplicateKeySafeLoader(yaml.SafeLoader):
    """SafeLoader that raises ConstructorError on duplicate mapping keys."""


def _no_duplicates_constructor(loader: yaml.Loader, node: yaml.Node, deep: bool = False) -> dict:
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None, None,
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
    """Return a human-readable description of the first duplicate-key violation,
    or None when the file parses cleanly under the strict loader."""
    try:
        with open(path, encoding="utf-8") as f:
            yaml.load(f, Loader=_DuplicateKeySafeLoader)
        return None
    except yaml.constructor.ConstructorError as e:
        mark = getattr(e, "problem_mark", None) or e.context_mark
        line = (mark.line + 1) if mark else 1
        return f"line {line}: {e.problem}"
    except (yaml.YAMLError, OSError):
        # Other parse errors are surfaced by SCH-001/010/014 — skip here.
        return None


# ── POL-010: hidden / OS-artefact files blocked from any PR ──────────────────

_BLOCKED_FILENAMES = frozenset({
    ".DS_Store", "Thumbs.db", "desktop.ini",
})
_BLOCKED_BASENAME_SUFFIXES = (".swp", ".swo", ".bak", "~")
_BLOCKED_PREFIXES = (".idea/", ".vs/", ".vscode/.cache/")
_BLOCKED_ENV_NAMES = (".env",)  # exact filename, plus .env.* variants below


def _is_env_artefact(rel: str) -> bool:
    name = Path(rel).name
    return name == ".env" or name.startswith(".env.")


def validate_against_schema(data: Any, schema: dict) -> list[str]:
    errors = []
    try:
        # B1: enable FormatChecker so format: email / format: uri actually fire.
        v = jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker())
        for error in sorted(v.iter_errors(data), key=lambda e: list(e.path)):
            path = ".".join(str(p) for p in error.path) or "(root)"
            errors.append(f"{path}: {error.message}")
    except Exception as e:
        errors.append(str(e))
    return errors


def is_agent_path(rel: str) -> bool:
    return rel.startswith("agents/")


def agent_folder_of(rel: str) -> Path | None:
    """
    Given a file path relative to repo root, return the agent folder it belongs to
    (the directory containing metadata.yaml). Returns None if it can't be determined.
    """
    parts = Path(rel).parts
    # Layout: agents/<name>/
    if len(parts) >= 2 and parts[0] == "agents":
        return Path(*parts[:2])
    return None


def readme_has_section(content: str, *headings: str) -> bool:
    """Return True if the README contains any of the given ## headings."""
    for h in headings:
        if re.search(rf"^##\s+{re.escape(h)}", content, re.MULTILINE | re.IGNORECASE):
            return True
    return False


# ── Failure collector ─────────────────────────────────────────────────────────

class Failure:
    def __init__(self, rule_id: str, file: str, message: str, line: int = 1):
        self.rule_id = rule_id
        self.file = file
        self.line = line
        self.message = message

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "file": self.file,
            "line": self.line,
            "message": self.message,
        }


# ── Checks ────────────────────────────────────────────────────────────────────

def check_structural(repo: Path, folders: set[Path], changed_files: list[str]) -> list[Failure]:
    failures = []

    for folder in folders:
        abs_folder = repo / folder
        rel = str(folder)

        # STR-001: metadata.yaml required everywhere
        if not (abs_folder / "metadata.yaml").exists():
            failures.append(Failure(
                "STR-001", f"{rel}/metadata.yaml",
                "metadata.yaml is missing. Every agent must include a metadata.yaml. "
                "See docs/schemas/metadata-schema.json"
            ))

        # STR-002: README.md required everywhere
        if not (abs_folder / "README.md").exists():
            failures.append(Failure(
                "STR-002", f"{rel}/README.md",
                "README.md is missing. Provide a usage guide for your agent."
            ))

        is_agent = folder.parts[0] == "agents"

        # STR-003: agent.yaml required for all agents
        if is_agent and not (abs_folder / "agent.yaml").exists():
            failures.append(Failure(
                "STR-003", f"{rel}/agent.yaml",
                "agent.yaml is required for every agent."
            ))

        # STR-005 / STR-006: tool.yaml + Dockerfile required in each tool folder
        tools_dir = abs_folder / "tools"
        if is_agent and tools_dir.is_dir():
            for tool_folder in [d for d in tools_dir.iterdir() if d.is_dir()]:
                if not (tool_folder / "tool.yaml").exists():
                    failures.append(Failure(
                        "STR-005", str((tool_folder / "tool.yaml").relative_to(repo)),
                        f"tool.yaml is missing in tools/{tool_folder.name}/. Every tool must have a tool.yaml definition."
                    ))
                if not (tool_folder / "Dockerfile").exists():
                    failures.append(Failure(
                        "STR-006", str((tool_folder / "Dockerfile").relative_to(repo)),
                        f"Dockerfile is missing in tools/{tool_folder.name}/. Tools require a Dockerfile."
                    ))

        # STR-009 (tools naming): detect directories that look like a misnamed tools/ folder.
        if is_agent:
            for subdir in abs_folder.iterdir():
                if not subdir.is_dir() or subdir.name == "tools":
                    continue
                has_tool_contents = (
                    (subdir / "tool.yaml").exists()
                    or any(
                        (d / "tool.yaml").exists()
                        for d in subdir.iterdir() if d.is_dir()
                    )
                )
                if has_tool_contents:
                    failures.append(Failure(
                        "STR-009", str(subdir.relative_to(repo)),
                        f"Directory '{subdir.name}' appears to be a misnamed tools directory. "
                        f"The tools subdirectory must be named exactly 'tools'. "
                        f"Rename '{subdir.name}/' to 'tools/'."
                    ))

        # STR-010: metadata.yaml.name must equal the agent folder name.
        if is_agent:
            meta_path = abs_folder / "metadata.yaml"
            if meta_path.exists():
                data, err = load_yaml(meta_path)
                if not err and isinstance(data, dict):
                    meta_name = data.get("name")
                    if meta_name and meta_name != folder.name:
                        failures.append(Failure(
                            "STR-010", str(meta_path.relative_to(repo)),
                            f"metadata.yaml: 'name' is '{meta_name}' but the agent folder is "
                            f"'{folder.name}'. The two must be identical; rename the folder "
                            f"or update 'name' so they match."
                        ))

        # STR-011: YAML files in this folder must not contain duplicate mapping keys.
        if is_agent:
            yaml_candidates = [abs_folder / "metadata.yaml", abs_folder / "agent.yaml"]
            tools_dir = abs_folder / "tools"
            if tools_dir.is_dir():
                for t in tools_dir.iterdir():
                    if t.is_dir() and (t / "tool.yaml").exists():
                        yaml_candidates.append(t / "tool.yaml")
            for ypath in yaml_candidates:
                if not ypath.exists():
                    continue
                dup_msg = find_duplicate_yaml_key(ypath)
                if dup_msg:
                    failures.append(Failure(
                        "STR-011", str(ypath.relative_to(repo)),
                        f"YAML duplicate mapping key detected ({dup_msg}). "
                        f"PyYAML silently keeps the last value when keys repeat; "
                        f"remove the duplicate to make the file unambiguous."
                    ))

    return failures


def check_schema(repo: Path, folders: set[Path], agent_schema: dict | None, tool_schema: dict | None, metadata_schema: dict | None = None) -> list[Failure]:
    failures = []
    valid_regions = load_valid_regions(repo)

    for folder in folders:
        abs_folder = repo / folder
        rel = str(folder)

        # ── metadata.yaml ────────────────────────────────────────────
        meta_path = abs_folder / "metadata.yaml"
        if meta_path.exists():
            data, err = load_yaml(meta_path)
            meta_rel = str(meta_path.relative_to(repo))

            if err or data is None:
                failures.append(Failure("SCH-001", meta_rel, f"metadata.yaml could not be parsed: {err}"))
                continue

            # SCH-001: full schema validation against docs/schemas/metadata-schema.json
            if metadata_schema:
                for schema_err in validate_against_schema(data, metadata_schema):
                    failures.append(Failure("SCH-001", meta_rel,
                        f"metadata.yaml does not conform to docs/schemas/metadata-schema.json: {schema_err}"))

            # SCH-001: required fields (belt-and-suspenders when schema not loaded)
            for field in ["name", "type", "version", "publisher", "description", "tags"]:
                if field not in data:
                    failures.append(Failure(
                        "SCH-001", meta_rel,
                        f"metadata.yaml is missing required field '{field}'."
                    ))

            # SCH-002: type enum
            if data.get("type") != "agent":
                failures.append(Failure("SCH-002", meta_rel, "metadata.yaml: 'type' must be 'agent'."))

            # SCH-004: tags not empty
            tags = data.get("tags", [])
            if not isinstance(tags, list) or len(tags) == 0:
                failures.append(Failure("SCH-004", meta_rel, "metadata.yaml: At least one tag is required for discovery."))
            else:
                # SCH-005: tag format
                for tag in tags:
                    if not isinstance(tag, str) or not TAG_RE.match(tag):
                        failures.append(Failure(
                            "SCH-005", meta_rel,
                            f"metadata.yaml: Tag '{tag}' is invalid. Tags must be lowercase and hyphen-separated "
                            "(e.g., 'clinical-trials')."
                        ))

            # SCH-006: region validation (optional field)
            regions = data.get("supported_regions", [])
            if regions:
                for region in regions:
                    if valid_regions and region not in valid_regions:
                        failures.append(Failure(
                            "SCH-006", meta_rel,
                            f"metadata.yaml: '{region}' is not a recognized Azure region alias. "
                            "See docs/schemas/metadata-schema.json#regions"
                        ))

            pub = data.get("publisher", {}) or {}

            # SCH-008: publisher.contact email
            contact = pub.get("contact", "")
            if not contact or not EMAIL_RE.match(str(contact)):
                failures.append(Failure(
                    "SCH-008", meta_rel,
                    "metadata.yaml: 'publisher.contact' must be a valid email address."
                ))

            # SCH-009: publisher.support_url HTTPS
            support_url = pub.get("support_url", "")
            if not support_url or not HTTPS_URL_RE.match(str(support_url)):
                failures.append(Failure(
                    "SCH-009", meta_rel,
                    "metadata.yaml: 'publisher.support_url' must be a valid HTTPS URL."
                ))

            # SCH-031: publisher.party (optional) must be '1p' or '3p' when present
            if "party" in pub and pub.get("party") not in ("1p", "3p"):
                failures.append(Failure(
                    "SCH-031", meta_rel,
                    "metadata.yaml: 'publisher.party' must be '1p' or '3p' when present."
                ))

            # SCH-016: version SemVer (if present)
            if "version" in data and not SEMVER_RE.match(str(data["version"])):
                failures.append(Failure(
                    "SCH-017", meta_rel,
                    "'version' must follow Semantic Versioning (e.g., '1.0.0')."
                ))

            # SCH-028/SCH-029: associated_tools checks
            is_agent_folder = folder.parts[0] == "agents"

            # SCH-028: associated_tools paths must exist on disk
            associated_tools = data.get("associated_tools", [])
            if is_agent_folder and isinstance(associated_tools, list):
                for tool_path_str in associated_tools:
                    tool_abs = repo / tool_path_str.rstrip("/")
                    if not tool_abs.is_dir():
                        failures.append(Failure(
                            "SCH-028", meta_rel,
                            f"metadata.yaml: associated_tools entry '{tool_path_str}' does not exist "
                            f"as a directory in this repository."
                        ))

            # SCH-029: if a tools/ directory exists, every sub-folder must be listed in associated_tools
            tools_dir = abs_folder / "tools"
            if is_agent_folder and tools_dir.is_dir():
                actual_tool_dirs = {
                    str(folder / "tools" / d.name).replace("\\", "/")
                    for d in tools_dir.iterdir() if d.is_dir()
                }
                declared = {p.rstrip("/") for p in (associated_tools if isinstance(associated_tools, list) else [])}
                missing = actual_tool_dirs - declared
                for m in sorted(missing):
                    failures.append(Failure(
                        "SCH-029", meta_rel,
                        f"metadata.yaml: tools directory '{m}' exists but is not listed in associated_tools. "
                        f"Add it to associated_tools or remove the tools directory."
                    ))
            elif is_agent_folder and isinstance(associated_tools, list) and associated_tools:
                # associated_tools is non-empty but no tools/ directory exists
                failures.append(Failure(
                    "SCH-029", meta_rel,
                    "metadata.yaml: associated_tools lists tool paths but no tools/ directory exists "
                    "under this agent folder."
                ))

        # ── agent.yaml ───────────────────────────────────────────────
        agent_path = abs_folder / "agent.yaml"
        if agent_path.exists() and agent_schema:
            data, err = load_yaml(agent_path)
            agent_rel = str(agent_path.relative_to(repo))

            if err or data is None:
                failures.append(Failure("SCH-010", agent_rel, f"agent.yaml could not be parsed: {err}"))
            else:
                # SCH-010: full schema validation
                schema_errors = validate_against_schema(data, agent_schema)
                for se in schema_errors:
                    failures.append(Failure(
                        "SCH-010", agent_rel,
                        f"agent.yaml failed schema validation against docs/schemas/agent-schema-v2.json: {se}"
                    ))

                # SCH-011: kind must be prompt
                if data.get("kind") != "prompt":
                    failures.append(Failure(
                        "SCH-011", agent_rel,
                        "agent.yaml: 'kind' must be 'prompt'. Only prompt agents are permitted in this repository."
                    ))

                # SCH-012: instructions non-empty
                instructions = data.get("instructions", "")
                if not instructions or not str(instructions).strip():
                    failures.append(Failure(
                        "SCH-012", agent_rel,
                        "agent.yaml: 'instructions' is required and must not be empty (max 32,000 characters)."
                    ))

                # SCH-036: instructions length cap
                if isinstance(instructions, str) and len(instructions) > 32000:
                    failures.append(Failure(
                        "SCH-036", agent_rel,
                        f"agent.yaml: 'instructions' is {len(instructions)} characters but the cap is 32,000. "
                        "Move auxiliary context out of the system prompt."
                    ))

                # SCH-013: name pattern
                name = data.get("name", "")
                if not name or not AGENT_NAME_RE.match(str(name)):
                    failures.append(Failure(
                        "SCH-013", agent_rel,
                        "agent.yaml: 'name' must start with a letter and contain only letters, digits, hyphens, or underscores."
                    ))

                # SCH-017: version SemVer
                if "version" in data and not SEMVER_RE.match(str(data.get("version", ""))):
                    failures.append(Failure(
                        "SCH-017", agent_rel,
                        "'version' must follow Semantic Versioning (e.g., '1.0.0')."
                    ))

                # SCH-030: agents with a tools/ directory must declare discoveryExtensions
                tools_dir_for_agent = abs_folder / "tools"
                if tools_dir_for_agent.is_dir() and not data.get("discoveryExtensions"):
                    failures.append(Failure(
                        "SCH-030", agent_rel,
                        "agent.yaml: 'discoveryExtensions' is required when the agent has a tools/ "
                        "directory. The discoveryExtensions node must declare the Discovery-managed "
                        "tools so they are wired up at deploy time. "
                        "See docs/authoring-guide.md for the expected structure."
                    ))

        # ── tool.yaml files ──────────────────────────────────────────
        tools_dir = abs_folder / "tools"
        if tools_dir.is_dir() and tool_schema:
            for tool_folder in [d for d in tools_dir.iterdir() if d.is_dir()]:
                tool_path = tool_folder / "tool.yaml"
                if tool_path.exists():
                    data, err = load_yaml(tool_path)
                    tool_rel = str(tool_path.relative_to(repo))

                    if err or data is None:
                        failures.append(Failure("SCH-014", tool_rel, f"tool.yaml could not be parsed: {err}"))
                        continue

                    # SCH-014: full schema validation
                    schema_errors = validate_against_schema(data, tool_schema)
                    for se in schema_errors:
                        failures.append(Failure(
                            "SCH-014", tool_rel,
                            f"tool.yaml failed schema validation against docs/schemas/tool-definition-schema.json: {se}"
                        ))

                    # SCH-015: infra_node referential integrity
                    infra_names = {i.get("name") for i in (data.get("infra") or []) if isinstance(i, dict)}
                    for action in (data.get("actions") or []):
                        node = action.get("infra_node")
                        if node and node not in infra_names:
                            failures.append(Failure(
                                "SCH-015", tool_rel,
                                f"tool.yaml: infra_node '{node}' does not match any entry in infra[].name."
                            ))
                    for env in (data.get("code_environments") or []):
                        node = env.get("infra_node")
                        if node and node not in infra_names:
                            failures.append(Failure(
                                "SCH-015", tool_rel,
                                f"tool.yaml: infra_node '{node}' does not match any entry in infra[].name."
                            ))

                    # SCH-017: version SemVer
                    if "version" in data and not SEMVER_RE.match(str(data.get("version", ""))):
                        failures.append(Failure(
                            "SCH-017", tool_rel,
                            "'version' must follow Semantic Versioning (e.g., '1.0.0')."
                        ))

                    # SCH-034: uniqueness within tool.yaml.
                    def _dupes(items: list[str]) -> list[str]:
                        seen: set[str] = set()
                        dups: list[str] = []
                        for it in items:
                            if it in seen and it not in dups:
                                dups.append(it)
                            seen.add(it)
                        return dups

                    infra_name_list = [
                        i.get("name") for i in (data.get("infra") or [])
                        if isinstance(i, dict) and i.get("name")
                    ]
                    action_name_list = [
                        a.get("name") for a in (data.get("actions") or [])
                        if isinstance(a, dict) and a.get("name")
                    ]
                    output_name_list: list[str] = []
                    mount_path_list: list[str] = []
                    for a in (data.get("actions") or []):
                        if not isinstance(a, dict):
                            continue
                        for omc in (a.get("output_mount_configurations") or []):
                            if isinstance(omc, dict) and omc.get("output_name"):
                                output_name_list.append(omc["output_name"])
                        for inf in (a.get("inline_files") or []):
                            if isinstance(inf, dict) and inf.get("mount_path"):
                                mount_path_list.append(inf["mount_path"])

                    for kind, items in (
                        ("infra[].name", infra_name_list),
                        ("actions[].name", action_name_list),
                        ("actions[].output_mount_configurations[].output_name", output_name_list),
                        ("actions[].inline_files[].mount_path", mount_path_list),
                    ):
                        dupes = _dupes(items)
                        if dupes:
                            failures.append(Failure(
                                "SCH-034", tool_rel,
                                f"tool.yaml: duplicate value(s) in {kind}: {dupes}. Each entry must be unique."
                            ))

                    # SCH-035: every name in actions[].input_schema.required must be defined
                    # under actions[].input_schema.properties.
                    for a in (data.get("actions") or []):
                        if not isinstance(a, dict):
                            continue
                        ischema = a.get("input_schema") or {}
                        props = (ischema.get("properties") or {})
                        required = ischema.get("required") or []
                        missing = [r for r in required if r not in props]
                        if missing:
                            failures.append(Failure(
                                "SCH-035", tool_rel,
                                f"tool.yaml: action '{a.get('name', '?')}' lists required input(s) "
                                f"{missing} that are not defined under input_schema.properties."
                            ))

    return failures


def check_policy(repo: Path, folders: set[Path], changed_files: list[str]) -> list[Failure]:
    failures = []

    for folder in folders:
        abs_folder = repo / folder
        rel = str(folder)

        meta_path = abs_folder / "metadata.yaml"
        if meta_path.exists():
            data, _ = load_yaml(meta_path)
            meta_rel = str(meta_path.relative_to(repo))
            if data:
                # POL-004: description length
                desc = data.get("description", "") or ""
                if not (10 <= len(str(desc).strip()) <= 500):
                    failures.append(Failure(
                        "POL-004", meta_rel,
                        "metadata.yaml: 'description' must be between 10 and 500 characters."
                    ))

        # POL-005: README.md min size
        readme_path = abs_folder / "README.md"
        if readme_path.exists():
            size = readme_path.stat().st_size
            if size < 100:
                failures.append(Failure(
                    "POL-005", str(readme_path.relative_to(repo)),
                    "README.md appears to be empty or too short. Provide a meaningful usage guide."
                ))

    # POL-008: no binary files (except validated model weights, see POL-009)
    for f in changed_files:
        ext = Path(f).suffix.lower()
        if ext in BLOCKED_BINARY_EXTENSIONS:
            failures.append(Failure(
                "POL-008", f,
                f"Binary file '{Path(f).name}' is not permitted in this repository. "
                "Container images must be hosted externally. "
                "Model weights may be checked in only as one of the formats listed "
                "in docs/authoring-guide.md (POL-009)."
            ))

    # POL-009: model-weight files must be (a) Git-LFS tracked, (b) under the
    # size cap, (c) header-validated against their declared extension, and
    # (d) for pickle-bearing formats, free of unsafe pickle opcodes.
    failures += check_model_weights(repo, changed_files)

    # POL-010: hidden / OS-artefact files are never allowed in any PR.
    for f in changed_files:
        name = Path(f).name
        rel_posix = f.replace("\\", "/")
        is_blocked = (
            name in _BLOCKED_FILENAMES
            or _is_env_artefact(rel_posix)
            or any(name.endswith(suf) for suf in _BLOCKED_BASENAME_SUFFIXES)
            or any(rel_posix.startswith(p) or f"/{p}" in f"/{rel_posix}" for p in _BLOCKED_PREFIXES)
        )
        if is_blocked:
            failures.append(Failure(
                "POL-010", f,
                f"File '{f}' is an OS artefact / editor state file and must not be committed. "
                f"Add it to .gitignore and remove it from the PR."
            ))

    # POL-011: .auto-registry/** is generated by CI. Hand-edits in a PR race with
    # the post-merge generator and corrupt the registry.
    for f in changed_files:
        rel_posix = f.replace("\\", "/")
        if rel_posix.startswith(".auto-registry/"):
            failures.append(Failure(
                "POL-011", f,
                "Files under .auto-registry/ are auto-generated by the update-registry.yml "
                "and update-starter-kits-registry.yml workflows. Remove your changes to "
                f"'{f}'; the registry will be rebuilt automatically after merge."
            ))

    return failures


def _is_ci() -> bool:
    """True when running in GitHub Actions (or any CI that sets the standard env).

    POL-009 must enforce strictly in CI; on a local dev box where git or LFS
    might be misconfigured, the same checks degrade to best-effort.
    """
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true"


def _is_lfs_tracked(repo: Path, rel_path: str) -> bool | None:
    """Return True/False if `git check-attr filter` reports lfs/non-lfs.

    Returns ``None`` if git is unavailable or the call fails. The caller is
    responsible for deciding what to do with ``None``: in CI we treat it as
    a hard POL-009 failure (the LFS check is a required gate); on a local
    dev box we fall back to allowing the file (best-effort) so that an
    environmental glitch doesn't block iteration.
    """
    try:
        out = subprocess.run(
            ["git", "check-attr", "filter", "--", rel_path],
            cwd=str(repo), capture_output=True, text=True, check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if out.returncode != 0:
        return None
    # Output format: "<path>: filter: lfs" (or "unspecified")
    return out.stdout.strip().endswith(": lfs")


def _is_lfs_tracked_strict(repo: Path, rel_path: str, ext: str) -> bool:
    """LFS check with the CI-vs-local fail-mode policy applied.

    - Definitive True / False from git: returned as-is.
    - Indeterminate (git missing, command failed): in CI we return False so
      the caller emits a hard POL-009 failure (an environmental glitch must
      not silently bypass a required gate); on a local dev box we return
      True so the developer isn't blocked by a misconfigured environment.
    """
    result = _is_lfs_tracked(repo, rel_path)
    if result is not None:
        return result
    if _is_ci():
        # Stderr breadcrumb so the cause is visible in the CI logs even
        # when the failure shows up as a generic POL-009 message.
        print(
            f"WARNING: could not determine LFS tracking status for {rel_path} "
            f"(extension {ext}) in CI; failing closed per POL-009.",
            file=sys.stderr,
        )
        return False
    print(
        f"WARNING: could not determine LFS tracking status for {rel_path} "
        f"(extension {ext}); allowing in non-CI mode (best-effort).",
        file=sys.stderr,
    )
    return True


def _picklescan_unsafe_imports(path: Path) -> list[str]:
    """Run picklescan on a torch ZIP and return any disallowed module imports.

    Returns an empty list if the file is clean. If ``picklescan`` is not
    installed, returns a single sentinel entry so the caller can surface a
    hard POL-009 failure: in a security gate, soft-passing on missing
    dependencies silently disables enforcement, which is exactly what the
    rule exists to prevent. The CI workflow installs picklescan as part of
    the validator step — the only way to hit this path in practice is a
    misconfigured local run, and that should fail loudly.
    """
    try:
        from picklescan.scanner import scan_file_path  # type: ignore
    except ImportError:
        return [
            "picklescan package is not installed; POL-009 requires it to "
            "validate pickle-bearing checkpoints. Install `picklescan` in "
            "the validator environment (the CI workflow does this)."
        ]

    try:
        result = scan_file_path(str(path))
    except Exception as e:
        return [f"picklescan error: {e}"]

    bad: list[str] = []
    for g in getattr(result, "globals", []) or []:
        module = getattr(g, "module", "") or ""
        name = getattr(g, "name", "") or ""
        if not module:
            continue
        # Allow exact module match or any submodule of an allow-listed root.
        root = module.split(".")[0]
        if module in PICKLE_ALLOWLIST or root in PICKLE_ALLOWLIST:
            continue
        bad.append(f"{module}.{name}")
    return bad


def check_model_weights(repo: Path, changed_files: list[str]) -> list[Failure]:
    """POL-009: header-validate every model-weights file in the diff."""
    failures: list[Failure] = []
    for f in changed_files:
        ext = Path(f).suffix.lower()
        if ext not in MODEL_WEIGHT_EXTENSIONS:
            continue
        path = repo / f
        if not path.is_file():
            # Deletion or missing checkout — nothing to validate.
            continue

        if not _is_lfs_tracked_strict(repo, f, ext):
            failures.append(Failure(
                "POL-009", f,
                "Model-weight files must be Git-LFS tracked. Add an entry to "
                ".gitattributes (or confirm the existing pattern matches) and "
                "re-commit with `git lfs track`."
            ))
            continue

        try:
            size = path.stat().st_size
        except OSError as e:
            failures.append(Failure("POL-009", f, f"Could not stat file: {e}"))
            continue
        if size > MODEL_WEIGHT_MAX_BYTES:
            failures.append(Failure(
                "POL-009", f,
                f"Model-weight file is {size} bytes, exceeding the "
                f"{MODEL_WEIGHT_MAX_BYTES} byte (5 GB) cap. Host it externally "
                f"and reference it from the Dockerfile instead."
            ))
            continue

        ok, detail = sniff(path)
        if not ok:
            failures.append(Failure(
                "POL-009", f,
                f"Model-weight header validation failed: {detail}"
            ))
            continue

        if ext in {".pt", ".pth", ".ckpt"}:
            bad = _picklescan_unsafe_imports(path)
            if bad:
                preview = ", ".join(bad[:5])
                more = "" if len(bad) <= 5 else f" (+{len(bad) - 5} more)"
                failures.append(Failure(
                    "POL-009", f,
                    f"picklescan flagged disallowed pickle imports: {preview}{more}. "
                    f"Re-export the checkpoint with safetensors or remove the "
                    f"unsafe globals."
                ))
    return failures


def check_documentation(repo: Path, folders: set[Path]) -> list[Failure]:
    failures = []

    for folder in folders:
        abs_folder = repo / folder
        parts = folder.parts
        is_agent = len(parts) >= 2 and parts[0] == "agents"

        readme_path = abs_folder / "README.md"
        if not readme_path.exists():
            continue

        try:
            content = readme_path.read_text(encoding="utf-8")
        except OSError:
            continue

        readme_rel = str(readme_path.relative_to(repo))

        # DOC-001: min size (also checked in POL-005 but DOC series checks structure)
        if len(content.strip()) < 50:
            failures.append(Failure("DOC-001", readme_rel,
                "README.md is missing or empty. Every agent must include a README.md."))
            continue

        # DOC-002: top-level heading
        if not re.search(r"^#\s+\S", content, re.MULTILINE):
            failures.append(Failure("DOC-002", readme_rel,
                "README.md must begin with a top-level heading (# Agent Name)."))

        # DOC-003: Overview / Description
        if not readme_has_section(content, "Overview", "Description"):
            failures.append(Failure("DOC-003", readme_rel,
                "README.md must include a '## Overview' or '## Description' section explaining what the agent does."))

        # DOC-004: Usage / Getting Started
        if not readme_has_section(content, "Usage", "Getting Started"):
            failures.append(Failure("DOC-004", readme_rel,
                "README.md must include a '## Usage' or '## Getting Started' section."))

        # DOC-005: Prerequisites
        if not readme_has_section(content, "Prerequisites"):
            failures.append(Failure("DOC-005", readme_rel,
                "README.md must include a '## Prerequisites' section listing any required permissions, services, or credentials."))

        if is_agent:
            # DOC-101: Architecture / How it works
            if not readme_has_section(content, "Architecture", "How it works"):
                failures.append(Failure("DOC-101", readme_rel,
                    "README.md must include an '## Architecture' or '## How it works' section."))

            # DOC-102: Tools section if tools/ present
            if (abs_folder / "tools").is_dir() and not readme_has_section(content, "Tools"):
                failures.append(Failure("DOC-102", readme_rel,
                    "README.md must include a '## Tools' section describing each tool when a tools/ directory is present."))

            # DOC-103: Configuration / Parameters
            if not readme_has_section(content, "Configuration", "Parameters"):
                failures.append(Failure("DOC-103", readme_rel,
                    "README.md must include a '## Configuration' or '## Parameters' section documenting agent inputs."))

            # DOC-104: Known Limitations
            if not readme_has_section(content, "Known Limitations", "Limitations"):
                failures.append(Failure("DOC-104", readme_rel,
                    "README.md must include a '## Known Limitations' section."))

            # DOC-105: Contributing
            if not readme_has_section(content, "Contributing") and "CONTRIBUTING.md" not in content:
                failures.append(Failure("DOC-105", readme_rel,
                    "README.md must include a '## Contributing' section or a link to CONTRIBUTING.md."))

        # DOC-006: forbid TODO / FIXME / XXX in README and YAML files.
        # Skip content inside fenced code blocks so legitimate code samples are not flagged.
        doc_files = [readme_path]
        for fname in ("metadata.yaml", "agent.yaml"):
            p = abs_folder / fname
            if p.exists():
                doc_files.append(p)
        for dpath in doc_files:
            try:
                text = dpath.read_text(encoding="utf-8")
            except OSError:
                continue
            stripped_text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
            for marker in ("TODO", "FIXME", "XXX"):
                m = re.search(rf"\b{marker}\b", stripped_text)
                if m:
                    line_no = stripped_text[:m.start()].count("\n") + 1
                    failures.append(Failure(
                        "DOC-006", str(dpath.relative_to(repo)),
                        f"Placeholder marker '{marker}' found at line {line_no}. "
                        f"Resolve or remove '{marker}' references before merging.",
                        line=line_no,
                    ))
                    break  # one finding per file is enough

    return failures


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_valid_regions(repo: Path) -> set[str]:
    regions_file = repo / "docs" / "schemas" / "azure-regions.json"
    if regions_file.exists():
        try:
            with open(regions_file, encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def discover_folders(repo: Path, changed_files: list[str]) -> set[Path]:
    """
    From the list of changed files, determine the unique agent/template
    folders they belong to.
    """
    folders: set[Path] = set()
    for f in changed_files:
        folder = agent_folder_of(f)
        if folder and (repo / folder).is_dir():
            folders.add(folder)
    return folders


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Validate a Discovery Catalog PR.")
    parser.add_argument("--changed-files", required=True,
                        help="Newline-delimited file listing changed paths (relative to repo root).")
    parser.add_argument("--repo-root", default=os.getcwd(),
                        help="Absolute path to repository root.")
    parser.add_argument("--output", default="validation-results.json",
                        help="Path to write JSON results.")
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()

    with open(args.changed_files, encoding="utf-8") as f:
        changed_files = [line.strip() for line in f if line.strip()]

    # Load schemas once
    agent_schema = load_json_schema(repo / "docs" / "schemas" / "agent-schema-v2.json")
    tool_schema = load_json_schema(repo / "docs" / "schemas" / "tool-definition-schema.json")
    metadata_schema = load_json_schema(repo / "docs" / "schemas" / "metadata-schema.json")

    if agent_schema is None:
        print("WARNING: docs/schemas/agent-schema-v2.json could not be loaded. SCH-010–013 skipped.", file=sys.stderr)
    if tool_schema is None:
        print("WARNING: docs/schemas/tool-definition-schema.json could not be loaded. SCH-014–015 skipped.", file=sys.stderr)
    if metadata_schema is None:
        print("WARNING: docs/schemas/metadata-schema.json could not be loaded. Full metadata schema validation skipped.", file=sys.stderr)

    folders = discover_folders(repo, changed_files)

    # Run ALL checks — collect everything before reporting
    failures: list[Failure] = []
    failures += check_structural(repo, folders, changed_files)
    failures += check_schema(repo, folders, agent_schema, tool_schema, metadata_schema)
    failures += check_policy(repo, folders, changed_files)
    failures += check_documentation(repo, folders)

    # Classify contribution type
    has_agents = any(is_agent_path(f) for f in changed_files)
    has_docs_only = all(f.startswith("docs/schemas/") for f in changed_files) if changed_files else False

    # Derive 1p / 3p classification from file contents (party field), NOT folder path.
    # Agent folders: read metadata.yaml -> party.
    # Starter-kit folders: read kit.json -> party.
    has_1p = False
    has_3p = False

    def _record_party(value: Any) -> None:
        nonlocal has_1p, has_3p
        if value == "1p":
            has_1p = True
        elif value == "3p":
            has_3p = True

    for folder in folders:
        meta_path = repo / folder / "metadata.yaml"
        if meta_path.exists():
            meta_data, _ = load_yaml(meta_path)
            if isinstance(meta_data, dict):
                pub = meta_data.get("publisher") or {}
                if isinstance(pub, dict):
                    _record_party(pub.get("party"))

    # Starter-kit folders touched by the PR
    kit_folders: set[Path] = set()
    for f in changed_files:
        parts = Path(f).parts
        if len(parts) >= 2 and parts[0] == "starter-kits":
            kit_folders.add(Path(*parts[:2]))
    for kit_folder in kit_folders:
        plugin_path = repo / kit_folder / "kit.json"
        if plugin_path.exists():
            try:
                with open(plugin_path, encoding="utf-8") as pf:
                    manifest = json.load(pf)
                if isinstance(manifest, dict):
                    _record_party(manifest.get("party"))
            except Exception:
                pass

    results = {
        "passed": len(failures) == 0,
        "failure_count": len(failures),
        "has_agents": has_agents,
        "has_docs_only": has_docs_only,
        "has_1p": has_1p,
        "has_3p": has_3p,
        "failures": [f.to_dict() for f in failures],
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # Print summary to stdout for CI logs
    if failures:
        print(f"\n❌ Validation failed — {len(failures)} issue(s) found:\n")
        for fail in failures:
            print(f"  [{fail.rule_id}] {fail.file}:{fail.line} — {fail.message}")
        sys.exit(1)
    else:
        print("\n✅ All validation checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
