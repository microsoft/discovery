#!/usr/bin/env python3
"""
update_registry.py

Scans agents/ folders and rebuilds .auto-registry/agent-registry.json from
metadata.yaml and agent.yaml files found in each contribution folder.

Usage:
    python update_registry.py [--repo-root <path>] [--output <path>]
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml is required. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

REGISTRY_VERSION = "1.0"

# Top-level scan roots mapped to entry type
SCAN_ROOTS = {
    "agents": "agent",
}


def load_yaml(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def extract_foundry_tools(agent_yaml: dict) -> list:
    """Return a list of Foundry-native tool names referenced in agent.yaml (e.g. web_search, mcp)."""
    tools = []
    for tool in agent_yaml.get("tools", []):
        if isinstance(tool, dict) and tool.get("name"):
            tools.append(tool["name"])
        elif isinstance(tool, str):
            tools.append(tool)
    return tools


def build_entry(folder_path: str, rel_path: str, entry_type: str) -> dict | None:
    metadata_path = os.path.join(folder_path, "metadata.yaml")
    agent_yaml_path = os.path.join(folder_path, "agent.yaml")

    if not os.path.isfile(metadata_path):
        return None

    metadata = load_yaml(metadata_path)
    agent_yaml = load_yaml(agent_yaml_path) if os.path.isfile(agent_yaml_path) else {}

    name = metadata.get("name") or metadata.get("display_name")
    if not name:
        return None

    version = str(metadata.get("version", "")).strip()
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        version = "0.0.0"

    pub = metadata.get("publisher") or {}
    publisher_name = pub.get("name") if isinstance(pub, dict) else str(pub)

    entry = {
        "name": name,
        "type": entry_type,
        "publisher_name": publisher_name or "",
        "path": rel_path.replace("\\", "/"),
        "version": version,
        "associated_tools": metadata.get("associated_tools") or [],
        "foundry_tools": extract_foundry_tools(agent_yaml),
        "supported_regions": metadata.get("supported_regions") or [],
        "description": metadata.get("description") or "",
        "tags": metadata.get("tags") or [],
    }

    return entry


def scan_repo(repo_root: str) -> list:
    entries = []

    for scan_dir, entry_type in SCAN_ROOTS.items():
        base_path = os.path.join(repo_root, scan_dir)
        if not os.path.isdir(base_path):
            continue

        # Flat structure: agents/<name>/
        for folder_name in sorted(os.listdir(base_path)):
            folder_path = os.path.join(base_path, folder_name)
            if not os.path.isdir(folder_path):
                continue
            rel_path = os.path.join(scan_dir, folder_name)
            entry = build_entry(folder_path, rel_path, entry_type)
            if entry:
                entries.append(entry)

    return entries


def main():
    parser = argparse.ArgumentParser(description="Rebuild .auto-registry/agent-registry.json from repo contents")
    parser.add_argument(
        "--repo-root",
        default=os.getcwd(),
        help="Path to repository root (default: cwd)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for registry.json (default: <repo-root>/.auto-registry/agent-registry.json)",
    )
    args = parser.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    output_path = args.output or os.path.join(repo_root, ".auto-registry", "agent-registry.json")

    # Load existing registry to report additions/removals
    existing_entries = []
    if os.path.isfile(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                existing_entries = json.load(f).get("entries", [])
        except Exception:
            pass

    existing_paths = {e["path"] for e in existing_entries}

    entries = scan_repo(repo_root)
    new_paths = {e["path"] for e in entries}

    added = new_paths - existing_paths
    removed = existing_paths - new_paths

    for path in sorted(added):
        print(f"  + added:   {path}")
    for path in sorted(removed):
        print(f"  - removed: {path}")
    if not added and not removed:
        print("  (no entries added or removed)")

    registry = {
        "version": REGISTRY_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": entries,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
        f.write("\n")

    print(f"Registry updated: {len(entries)} entries written to {output_path}")


if __name__ == "__main__":
    main()
