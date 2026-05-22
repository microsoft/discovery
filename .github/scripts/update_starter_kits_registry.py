#!/usr/bin/env python3
"""
update_starter_kits_registry.py — Post-merge generator for the starter kit catalog artifact.

Generates from all starter-kits/*/kit.json manifests:
  .auto-registry/starter-kit-registry.json — Full resolved catalog for Discovery UI.
                                             Includes computed availability, missingAgents,
                                             and inlined agentMeta for present agents.

Reads agent availability from .auto-registry/agent-registry.json (must be up-to-date before this runs).
Reads agent display metadata from agents/*/agent.yaml and agents/*/metadata.yaml.

Usage:
  python .github/scripts/update_starter_kits_registry.py --repo-root .
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


def load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def load_yaml_safe(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def get_commit_sha(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def get_kit_dirs(repo_root: Path) -> list[Path]:
    """Return all kit directories directly under starter-kits/."""
    kits = []
    base = repo_root / "starter-kits"
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if d.is_dir() and (d / "kit.json").exists():
                kits.append(d)
    return kits


def get_kit_relpath(repo_root: Path, kit_dir: Path) -> str:
    """Return canonical kit identifier, e.g. 'protein-structure-analysis'."""
    return str(kit_dir.relative_to(repo_root / "starter-kits")).replace(os.sep, "/")


def build_registry_path_set(registry: dict) -> set[str]:
    """Return set of agent paths from .auto-registry/agent-registry.json."""
    return {
        e["path"]
        for e in registry.get("entries", [])
        if e.get("type") == "agent"
    }


def load_agent_meta(repo_root: Path, ref: str) -> dict | None:
    """Load name/displayName/version/tags/description for an agent ref from its files."""
    agent_dir = repo_root / ref
    metadata_path = agent_dir / "metadata.yaml"
    agent_yaml_path = agent_dir / "agent.yaml"

    if not metadata_path.exists():
        return None

    try:
        meta = load_yaml_safe(metadata_path)
    except Exception:
        return None

    name = meta.get("name") or meta.get("display_name") or ref.split("/")[-1]

    # displayName: prefer agent.yaml .displayName, fall back to metadata.yaml name
    display_name = name
    if agent_yaml_path.exists():
        try:
            agent_def = load_yaml_safe(agent_yaml_path)
            display_name = agent_def.get("displayName") or name
        except Exception:
            pass

    return {
        "name": name,
        "displayName": display_name,
        "version": meta.get("version", ""),
        "tags": meta.get("tags", []),
        "description": meta.get("description", ""),
    }


def compute_availability(
    manifest: dict,
    agent_path_set: set[str],
) -> tuple[str, list[str]]:
    """
    Returns (availability, missingAgents).
    availability: "healthy" | "degraded"
    missingAgents: list of ref strings absent from registry (both required and optional)
    """
    lifecycle = manifest.get("lifecycle", "active")
    agent_refs = manifest.get("agentRefs", [])

    if lifecycle == "archived":
        # Archived kits always report healthy; missingAgents still populated for information
        missing_all = [r["ref"] for r in agent_refs if r.get("ref") and r["ref"] not in agent_path_set]
        return "healthy", missing_all

    missing_required = []
    missing_all = []
    for ref_entry in agent_refs:
        ref = ref_entry.get("ref", "")
        if ref and ref not in agent_path_set:
            missing_all.append(ref)
            if ref_entry.get("required", False):
                missing_required.append(ref)

    availability = "degraded" if missing_required else "healthy"
    return availability, missing_all


def build_kit_registry_entry(
    manifest: dict,
    kit_dir: Path,
    kit_relpath: str,
    repo_root: Path,
    agent_path_set: set[str],
    generated_at: str,
) -> dict:
    """Build one entry for .auto-registry/starter-kit-registry.json.

    The entry is a deep copy of the kit.json manifest (which conforms to
    docs/schemas/starter-kit-schema.json), augmented with four top-level
    computed fields (`availability`, `missingAgents`, `computedAt`, `kitPath`)
    and with each `agentRefs[]` entry enriched with an `agentMeta` object
    pulled from the referenced agent's metadata.yaml / agent.yaml.
    """
    availability, missing_agents = compute_availability(manifest, agent_path_set)

    # Deep copy manifest so we can safely augment it
    entry = json.loads(json.dumps(manifest))

    # Enrich each top-level agentRefs[] entry with agentMeta when the agent
    # is present in the registry. agentRefs lives at the top level per the
    # current starter-kit-schema.json.
    enriched_refs = []
    for ref_entry in manifest.get("agentRefs", []):
        ref = ref_entry.get("ref", "")
        enriched = dict(ref_entry)
        if ref and ref not in missing_agents:
            agent_meta = load_agent_meta(repo_root, ref)
            if agent_meta:
                enriched["agentMeta"] = agent_meta
        enriched_refs.append(enriched)
    entry["agentRefs"] = enriched_refs

    entry["availability"] = availability
    entry["missingAgents"] = missing_agents
    entry["computedAt"] = generated_at
    entry["kitPath"] = f"starter-kits/{kit_relpath}"
    return entry


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate starter-kit-registry.json")
    parser.add_argument("--repo-root", required=True, help="Repository root directory")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()

    # Load .auto-registry/agent-registry.json (must exist — update-registry.yml runs before this)
    registry_path = repo_root / ".auto-registry" / "agent-registry.json"
    if not registry_path.exists():
        print(f"ERROR: .auto-registry/agent-registry.json not found at {registry_path}", file=sys.stderr)
        sys.exit(1)
    registry = load_json(registry_path)
    agent_path_set = build_registry_path_set(registry)
    print(f"Loaded registry with {len(agent_path_set)} agent paths")

    # Discover all kit dirs
    if not (repo_root / "starter-kits").is_dir():
        print("No starter-kits/ directory found. Nothing to generate.")
        sys.exit(0)

    kit_dirs = get_kit_dirs(repo_root)
    kit_relpaths = [get_kit_relpath(repo_root, d) for d in kit_dirs]
    print(f"Found {len(kit_dirs)} kit(s): {kit_relpaths}")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commit_sha = get_commit_sha(repo_root)

    registry_kits = []
    errors = []

    for kit_dir, kit_relpath in zip(kit_dirs, kit_relpaths):
        plugin_path = kit_dir / "kit.json"
        try:
            manifest = load_json(plugin_path)
        except Exception as e:
            errors.append(f"[{kit_relpath}] Failed to load kit.json: {e}")
            continue

        registry_kits.append(
            build_kit_registry_entry(manifest, kit_dir, kit_relpath, repo_root, agent_path_set, generated_at)
        )
        print(f"  Processed {kit_relpath}")

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)

    # Write .auto-registry/starter-kit-registry.json
    registry_output = {
        "schemaVersion": "1.0.0",
        "generatedAt": generated_at,
        "commitSha": commit_sha,
        "kits": registry_kits,
    }
    registry_out_path = repo_root / ".auto-registry" / "starter-kit-registry.json"
    write_json(registry_out_path, registry_output)
    print(f"Wrote {registry_out_path}")

    # Summary
    healthy = sum(1 for k in registry_kits if k.get("availability") == "healthy")
    degraded = sum(1 for k in registry_kits if k.get("availability") == "degraded")
    print(f"\n✓ Done. {len(registry_kits)} kit(s): {healthy} healthy, {degraded} degraded.")


if __name__ == "__main__":
    main()
